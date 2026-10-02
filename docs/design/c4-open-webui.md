# C4: Open WebUI in the app registry

**2026-10-01. Built and pinned 2026-10-02** ([record](../acceptance/c4-open-webui-run.md): 39 of 39 on GitHub's Windows and Ubuntu runners). Slice C4 of
[`workbench.md`](workbench.md) §7: the first app in the registry that we did
not write. Built on C1 (an account per app), C2 (sign-in with Eugene) and C3
(the registry's first entry, Workbench).

## Calls taken (Troy, 2026-10-01)

1. **Email:** Open WebUI will not sign anyone in without an email address,
   and Eugene's sign-in had none. **People get an optional email in Eugene**,
   and sign-in carries it. Whoever has none (the owner, today) gets Open
   WebUI's own placeholder (`ENABLE_OAUTH_EMAIL_FALLBACK`).
   Signing in to Eugene with Google or Microsoft is wanted too, as its own
   slice: [control #4](https://github.com/eugene-plexus/control/issues/4).
2. **Settings:** Open WebUI keeps its settings in its own database and ignores
   the environment after its first start. **Keep its settings, and reset
   them for one start only when Eugene's connection details change** (the
   gateway's address or the app's key).
3. **Licence:** install it **unmodified from PyPI**, with a catalogue card
   that calls it a separate project under its own licence, links the licence,
   and states its size. Nothing about its branding is changed.

## 0. Measured: Open WebUI 0.11.4 (released 2026-09-21)

On CPython 3.12.10 with uv 0.12.18, in a scratch environment. File references
are inside `open_webui/` at 0.11.4.

- **Python:** `>=3.11,<3.13`, so 3.12 is the newest allowed.
- **Size:** 245 packages, 1.8 GB, installed in 36 s with a warm cache.
  torch (CPU), sentence-transformers, faster-whisper, chromadb and OpenCV come
  with it.
- **Downloads at first start:** an embedding model, 933 MB from Hugging Face.
  `RAG_EMBEDDING_ENGINE=openai` stops it (measured), and so does
  `OFFLINE_MODE=true`. Whisper downloads on first local transcription;
  `AUDIO_STT_ENGINE=openai` stops it.
- **Start:** `open-webui serve --host H --port P`. Its default is
  `0.0.0.0:8080`, our gateway's port, so both are always passed. There is no
  `python -m open_webui`; the console script calls `open_webui:app`.
- **Writes:** without settings it writes into its own package (`data/`,
  `static/`, which it deletes and recopies at each start) and a secret-key file
  into the working directory. With `DATA_DIR`, `STATIC_DIR`, `HF_HOME` and
  `WEBUI_SECRET_KEY` set, nothing is written outside the data directory except
  `.pyc` files.
- **Secrets are values, never files**, in the Python server
  (`WEBUI_SECRET_KEY_FILE` exists only in its shell scripts).
- **Persistence:** every non-OAuth setting is copied into its database at first
  start, and the database wins afterwards. Measured: a restart with a new
  `OPENAI_API_KEY` kept the old one. `RESET_CONFIG_ON_START=true` clears them
  for that start. Sign-in settings are re-read at every start.
- **Sign-in (OpenID Connect):**
  - It registers a provider from `OPENID_PROVIDER_URL`, `OAUTH_CLIENT_ID`
    and `OAUTH_CLIENT_SECRET`. It sends people back to
    `/oauth/oidc/callback` on the address they used, and authenticates with
    `client_secret_basic`.
  - PKCE is used only with `OAUTH_CODE_CHALLENGE_METHOD=S256`.
  - It **requires an email**. Without one it answers 400 *"The email or
    password provided is incorrect"*, unless `ENABLE_OAUTH_EMAIL_FALLBACK`
    gives `oidc@<sub>.local`. It does not check the address's format, and a
    taken address is refused.
  - **The first person in becomes its admin.** After that, everyone is
    `pending` unless role management is on (`ENABLE_OAUTH_ROLE_MANAGEMENT`,
    `OAUTH_ROLES_CLAIM`, `OAUTH_ADMIN_ROLES`, `OAUTH_ALLOWED_ROLES`).
- **Its tools and functions are Python its admin pastes in**, run with `exec`
  in the server process. Nothing turns that off, so the entry declares
  `localActions: true`, and installs only where apps get an account of their
  own (C1).
- **Ready:** `/ready` answers 503 until startup completes. The first start
  took about 73 s, and later starts 11-15 s. Idle memory: 0.7 GB working
  set, 2.1-2.3 GB private.
- **Log export over OpenTelemetry** needs nine packages its PyPI release does
  not declare, and sends protobuf only. **Not used:** C1's launcher already
  forwards what it prints to the machine's Logs page.
- **Licence:** BSD-3-style plus a branding clause. Its name and logo may not
  be altered, removed or replaced in any deployment, unless the deployment
  has 50 or fewer users in 30 days, the holder gives written permission, or
  there is an enterprise licence. Its name may not endorse ours. Installing
  it unmodified on the user's own machine redistributes nothing.

## 1. What the registry learns (once, for every third-party entry)

`AppManifest` (agent.yaml) gains these fields. Workbench's entry needs none
of them and does not change.

| Field | What it says |
| --- | --- |
| `source: pypi` | Install `<package>==<version>` from the Python Package Index. `version` must then be an exact release. An archive URL stays the other form. |
| `entry: module:attribute` | A console-script function, called the way its own script calls it, with `args` as its arguments. A bare module keeps meaning `python -m`. |
| `args` | The arguments, with placeholders. |
| `environment` | The app's own variables, set from placeholders. This is how an app that does not read `EUGENE_PLEXUS_APP_*` is told where things are. |
| `healthPath` | Where readiness is answered, `/healthz` by default. |
| `resetOnConnectionChange` | A variable set to `true` for one start when the gateway's address or the app's key differs from the last start's (call 2). |
| `licenseUrl` | Where the app's own licence is read. The catalogue card links it beside the homepage (call 3). Display only. |

**Placeholders:** `{bindHost}`, `{port}`, `{dataDir}`, `{gatewayUrl}`,
`{appUrl}` (the address the console opens it at), `{oidcIssuer}`,
`{oidcClientId}`, and three secrets:
- `{clientKey}`;
- `{oidcClientSecret}`;
- `{appSecret}`, a random value made once and kept in the app's data
  directory.

**Secrets are filled in by the launcher, inside the app's own account**, from
the files it already reads. They never appear in the spec the agent writes,
in the agent's logs, or in the service definition. They do sit in the app's
own process environment, readable only by that account and an administrator,
because Open WebUI takes no other form.

## 2. The entry

```yaml
- id: open-webui
  name: Open WebUI
  summary: >-
    A widely used chat interface, by a separate project, under its own
    licence. Installed unmodified. About 1.8 GB on disk and up to 2 GB of
    memory.
  homepage: https://openwebui.com
  licenseUrl: https://github.com/open-webui/open-webui/blob/v0.11.4/LICENSE
  source: pypi
  version: 0.11.4
  package: open-webui
  entry: open_webui:app
  args: [serve, --host, "{bindHost}", --port, "{port}"]
  python: "3.12"
  ui: true
  configTrio: false
  uses: [inference]
  signIn: true
  signInCallbackPath: /oauth/oidc/callback
  healthPath: /ready
  localActions: true
  resetOnConnectionChange: RESET_CONFIG_ON_START
  environment:
    DATA_DIR: "{dataDir}"
    STATIC_DIR: "{dataDir}/static"
    HF_HOME: "{dataDir}/hf"
    WEBUI_SECRET_KEY: "{appSecret}"
    WEBUI_URL: "{appUrl}"
    CORS_ALLOW_ORIGIN: "{appUrl}"
    OPENAI_API_BASE_URL: "{gatewayUrl}/v1"
    OPENAI_API_KEY: "{clientKey}"
    ENABLE_OLLAMA_API: "false"
    RAG_EMBEDDING_ENGINE: openai
    AUDIO_STT_ENGINE: openai
    OFFLINE_MODE: "true"
    ENABLE_VERSION_UPDATE_CHECK: "false"
    ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS: "false"
    SCARF_NO_ANALYTICS: "true"
    DO_NOT_TRACK: "true"
    ANONYMIZED_TELEMETRY: "false"
    ENABLE_SIGNUP: "false"
    ENABLE_LOGIN_FORM: "false"
    ENABLE_OAUTH_SIGNUP: "true"
    OAUTH_PROVIDER_NAME: Eugene
    OPENID_PROVIDER_URL: "{oidcIssuer}/.well-known/openid-configuration"
    OAUTH_CLIENT_ID: "{oidcClientId}"
    OAUTH_CLIENT_SECRET: "{oidcClientSecret}"
    OAUTH_CODE_CHALLENGE_METHOD: S256
    OAUTH_SCOPES: openid email profile
    OAUTH_EMAIL_CLAIM: email
    OAUTH_USERNAME_CLAIM: name
    ENABLE_OAUTH_EMAIL_FALLBACK: "true"
    ENABLE_OAUTH_ROLE_MANAGEMENT: "true"
    OAUTH_ROLES_CLAIM: eugene_role
    OAUTH_ADMIN_ROLES: operator
    OAUTH_ALLOWED_ROLES: operator,member
```

- **The owner is its admin, and each person is an ordinary user**, from
  `eugene_role`. Workbench reads the same claim. Nobody waits in `pending`.
  Open WebUI takes a single-string roles claim as a one-item list
  (`utils/oauth.py:1565-1572`).
- **Embeddings and transcription go to the gateway**, through the app's key.
  A document upload works when the install serves an embedding model.
- **Its own web search stays off.** It runs from the app with its own search
  keys rather than the install's search account. Pointing it at the hub's
  search is later work.
- **`CORS_ALLOW_ORIGIN` is narrowed to its own address.** Its default is `*`,
  and its session cookie is readable by script (`httponly=False`, its choice).

## 3. Eugene's side: an optional email for each person

- `Person`, `PersonCreateRequest`, `PersonUpdateRequest` and `SnapshotPerson`
  gain `email`, optional and unique case-folded. `null` on an update clears
  it. It rides the existing `OP_PUT_PERSON`, so no new log operation is
  needed.
- Sign-in adds the **`email` scope**. With it, a person who has an email gets
  `email` and `email_verified: false`. Eugene sends no mail and has proved
  nothing, so it says so.
- **The People page** gets an Email field, which says what it is for: apps
  such as Open WebUI identify people by it.
- **The owner has no email in this slice.** Storing one belongs with the
  owner's profile and with control #4.

## 4. Acceptance

Apps with `localActions: true` install only where apps get accounts of their
own. So the run is on **GitHub's Windows and Ubuntu runners**, like C1's, and
on a Linux system install in WSL. Checks:

- **Install:** it installs from the catalogue at its pinned version, in an
  account of its own, and answers `/ready`.
- **Writes:** nothing is written outside its data directory, and nothing is
  downloaded from Hugging Face.
- **Sign-in through Eugene's page:**
  - the owner arrives as its admin;
  - a person with an email arrives as a user with that address;
  - a person without one gets the placeholder;
  - a disabled person cannot sign in.
- **Chat:** a chat answers through the gateway on the app's key, and the
  gateway's records show that key.
- **A rotated key:** after the key changes, the next start takes the new key,
  and a start with no change keeps an admin setting.
- **Uninstall:** it removes the account, the sign-in client and the key.

Plus a sabotage pass, every specs CI script run locally before the pin, and
both installers re-pinned.

## 5. Not in this slice

- Google and Microsoft sign-in (control #4), and the owner's email.
- Open WebUI's web search on the hub's search account, its image generation
  on the hub's images door, and its log export over OpenTelemetry.
- An update path beyond reinstalling at the next pinned version.
