# Row 34: Open WebUI: search and images through Eugene, safe updates, and `ENABLE_PLUGINS`

Lane AG2, third in its lane. Cross-component, size M+ (split below). Repos:
specs, gateway, agent, ui. The tool-driver does not change.

Sources: `c4-open-webui.md` (§0 "Corrected 2026-10-03", §5 "Not in this
slice"); memory `project_c4_open_webui` (the MR6 privacy defect); agent
`apps_catalogue.yaml`, `app_launcher.py`, `apps.py`, `routes/apps.py`;
gateway `server_tools.py`, `tool_client.py`.

## 1. What it delivers

- **Web search in Open WebUI uses the install's search accounts.** A new gateway door, `POST /v1/web_search`, answers in the shape that Open WebUI's "external" search engine reads. Open WebUI holds no search key of its own.
- **Image generation in Open WebUI uses the install's image model** through the gateway's images door.
- **Reset Open WebUI's settings to Eugene's.** One button on the app page restarts Open WebUI once with `RESET_CONFIG_ON_START`. Open WebUI keeps the settings from its first start, so this is how an image model or a search account added later reaches it.
- **An update cannot lose chats.** Before the first start of a new version, the agent copies Open WebUI's database. If the new version does not start, **Go back to 0.11.4** restores the copy and the previous version.
- **The Update button says when it resets settings.**
- **`ENABLE_PLUGINS` is decided** and written in the entry.
- **The pin moves to the current release**, checked by a drift script.

## 2. The design

### The search door (gateway, `gateway.yaml`)

`POST /v1/web_search` (operationId `webSearch`):

- Request: `{query: string 1..2000, count?: integer 1..20}`. These are the fields that Open WebUI's external engine sends.
- 200: a JSON array of `{link, title, snippet}`, at most `count` items, and at most the account's own result count. The door shortens the list. It does not change `SearchRunner`.
- It runs `server_tools.SearchRunner` on the install's search accounts in their order, as a chat's `web_search` does, with the same failover rule.
- Admission is the same as for every door: the key's tool scope must include `web_search`. Admission counts the request against the key's limits and attributes it.
- A `google` account is skipped. Google's terms require its Search Suggestions with its results (GS1, GS4), and this shape cannot carry them. The account's settings page says so.

Failures:

- 400: "query: must be 1 to 2000 characters."
- 403: `why_not`'s words. Example: "this key is local-only, and a web search sends a query made from the prompt to the internet".
- 503 with no usable account: "no search account is set up; add one under Backends, then Add a search account".
- 503 with only a Google account: "The install's only search account is Google. Its terms require its Search Suggestions shown with its results, and Open WebUI cannot show them. Add a Brave or SearXNG account."
- 503 when every account failed: the cause from each account (`SearchRunner`'s `reasons`).
- 429 carries the provider's `Retry-After`.

Files: a new `web_search_door.py` (parse and shape) and a new `routes/web_search.py`. It is not in `routes/inference.py`, which rows 1 and 55 own. Also `app.py` (router and body limit), `cors.py`, and one line in `admission.py` (see §6).

### The entry (`apps_catalogue.yaml`)

**Step 1, before any code:** install the target version in a scratch venv. Read its `config.py` and `env.py` for each name below, and record the line numbers in the entry's comments, as the MR6 comment does. The names below are from earlier releases. Step 1 finds the renames.

```yaml
    ENABLE_WEB_SEARCH: "true"
    WEB_SEARCH_ENGINE: external
    EXTERNAL_WEB_SEARCH_URL: "{gatewayUrl}/v1/web_search"
    EXTERNAL_WEB_SEARCH_API_KEY: "{clientKey}"
    WEB_SEARCH_RESULT_COUNT: "5"
    WEB_SEARCH_CONCURRENT_REQUESTS: "2"
    BYPASS_WEB_SEARCH_WEB_LOADER: "true"
    ENABLE_IMAGE_GENERATION: "{imageModelSet}"
    IMAGE_GENERATION_ENGINE: openai
    IMAGE_GENERATION_MODEL: "{imageModel}"
    ENABLE_PLUGINS: "true"
```

- **`BYPASS_WEB_SEARCH_WEB_LOADER: true`.** Open WebUI uses the provider's snippets and does not fetch each page from its own account. Every other Eugene door works this way. Its admin can change it in Admin Settings.
- **`WEB_SEARCH_CONCURRENT_REQUESTS: 2`.** Everyone in Open WebUI shares one app key, with 8 requests at once and 600 a minute. One search turn is a query-writing call, up to three searches and the answer. Two searches at once leave room for other people.
- **Step 1 also checks `OFFLINE_MODE`.** If `OFFLINE_MODE: "true"` turns web search off, the entry removes it and sets the narrower variables it stood for, each with its own line.

### Two new placeholders (agent `app_launcher.py`; `agent.yaml` prose)

- **`{imageModel}`** is the first model that the app's key lists with surface `image`. A local model comes before an external one, and a running model before a stopped one. Unlike `{embeddingModel}`, an external model is allowed: a prompt goes to it only when a person asks for an image. When there is none, the variable is unset and the start note says why.
- **`{imageModelSet}`** is `true` when `{imageModel}` has a value, else `false`. So Open WebUI is never told to make images with no model.
- **Neither changes the digest.** Both are filled values, not templates, so `connection_changed` is not affected.
- **The launcher writes `given.json`** in the data directory at each start that seeds settings (the first start or a reset start). It holds the time and the filled values that are not secret: search on, the image model, the search model and the result sorter. The app page reads it.

### Reset to Eugene's settings (`agent.yaml`; agent `routes/apps.py`)

- **The route.** `POST /v1/apps/{id}/restart` takes an optional body `{resetSettings: true}`, with an operator session. For a manifest without `resetOnConnectionChange`, it answers 409: "This app has no settings for Eugene to reset."
- **How it works.** The agent writes `connection.sha256` as `reset-requested`, then restarts the app. The launcher sees a digest that differs, sets the variable for one start, and writes the real digest.
- **App page.** "Eugene gave Open WebUI its settings on 21 Oct: search through Eugene, images with gpt-image-1, documents with nomic-embed-text."
- **When the gateway now serves a model the app was not given.** "Eugene now serves gpt-image-1, which Open WebUI was not given. Reset Open WebUI's settings."
- **The confirmation.** "Reset Open WebUI's settings to Eugene's? It restarts, and its Admin Settings go back to Eugene's. Chats, people, knowledge, models and tools stay."

### Updates (34b)

- **`AppManifest.updateBackup`.** The entry lists the paths under `{dataDir}` that the agent copies before the first start on a new version. For Open WebUI: `[webui.db, vector_db]`. Open WebUI migrates its database at start, and an older version cannot read a migrated one.
- **The backup** (agent `apps.py`, `installed_callback`). The agent copies the paths to `<app dir>/backups/<from-version>/`. It checks free space first and needs 1.2 times the size: "The update was not started: Open WebUI's data needs 3.1 GB for its backup, and D: has 1.2 GB free." The agent keeps one backup, and the next successful update replaces it.
- **Go back.** `POST /v1/apps/{id}/rollback` needs an operator session. It is offered while a backup and a `previousVersion` exist. It stops the app, restores the backup, makes `previousVersion` current, and starts the app. The confirmation: "Go back to Open WebUI 0.11.4? Chats and settings return to how they were before the update on 21 Oct. Anything written since then is lost."
- **A failed start.** When the new version fails its health check past the crash threshold, the app page shows first: "Open WebUI 0.12.3 did not start: {cause}. Go back to 0.11.4". Nothing goes back automatically, because automatic rollback is banked.
- **`AppCatalogueEntry.resetsSettings: boolean`.** It is true for a manifest with `resetOnConnectionChange` when the catalogue's `environment` differs from the installed one. The Update confirmation then adds: "This update resets Open WebUI's Admin Settings to Eugene's, once."
- **The drift script** (`specs/scripts/open-webui-drift.py <version>`). It downloads the wheel without installing it, then reports:
  - each name the entry sets that the version no longer reads;
  - each `*_BASE_URL` that falls back to `OPENAI_API_BASE_URL` or `api.openai.com` and that the entry does not set;
  - the default of `ENABLE_PLUGINS`.

  Any finding gives exit 1. The person who moves the pin runs it, and the C4 acceptance runs it on the pin.
- **The pin moves with the new variables**, in one change. Existing installs then reset once, not twice.

### `ENABLE_PLUGINS` (call 1)

Measured on 2026-10-03 at 0.11.4: `ENABLE_PLUGINS` (an `env.py` setting, default true) stops tool and function code from loading. The code interpreter and the terminals run code by other paths, and nobody has checked them. Because it is an `env.py` setting, Open WebUI's admin cannot change it in its own UI.

**Recommendation:** keep it on, write `"true"` in the entry, and keep `localActions: true`.

- **The app's own account is the protection.** It contains a pasted function, and it also contains Open WebUI's own defects. Turning plugins off would not make it safe to run Open WebUI in Eugene's account, where the install's keys are.
- **People choose Open WebUI for these features.** Tools and functions (pipes, filters, actions) are one of the main reasons.
- **Writing it fixes the behaviour** if upstream changes the default, and the app page can state it: "Tools and functions: on. They run in Open WebUI's own account."

Out of this row: Open WebUI on installs where apps get no account of their own (the NAS container, per-user installs, macOS). That needs every server-side code path measured as closed, and its own review.

### Defaults

- Search is on. Images are on when an image model is served. Plugins are on.
- **These defaults delete data, on a click only.** Go back discards everything written after the update. Reset clears Open WebUI's Admin Settings, but not its chats.
- **Settings are reset once at the update.** Existing installs lose their Open WebUI admin settings once, when the new entry arrives, as MR6 did (call 3).

## 3. Repositories and files

- **specs:**
  - `gateway.yaml`: the door;
  - `agent.yaml`: placeholder prose, `resetSettings`, `updateBackup`, `resetsSettings` and the rollback route;
  - `scripts/open-webui-drift.py`;
  - `scripts/c4-open-webui-acceptance.py`, extended;
  - `c4-open-webui.md`: the decisions and what building found.
- **gateway:** `web_search_door.py`, `routes/web_search.py`, `app.py`, `cors.py`, one line in `admission.py`, and tests.
- **agent:** `apps_catalogue.yaml`, `app_launcher.py`, `apps.py`, `routes/apps.py`, and tests.
- **ui:**
  - `src/app/apps/app/page.tsx`: the given settings, Reset and Go back;
  - `src/app/apps/page.tsx`: the Update confirmation;
  - the Google search account's note.
- **tool-driver:** no change.
- **Codegen.** Regenerate every consumer whose codegen names `gateway.yaml` or `agent.yaml`, and diff. Re-pin gateway, agent and ui. Control generates `agent_models.py` but uses none of this.

## 4. Tests that fail before the change

- **gateway `tests/test_web_search_door.py::test_answers_in_open_webui_shape`.** A client key and a stand-in tool-driver give 200 and a list of `{link, title, snippet}`. Today the route does not exist, so the request gets 404.
- **Also in gateway:** `test_local_only_key_refused` and `test_google_account_skipped`. The existing front-door path test fails until the door has its admission row.
- **agent `tests/test_app_launcher.py::test_image_model_placeholder`.** A listing with one image model fills `{imageModel}`, and `{imageModelSet}` becomes `true`. Today the launcher raises "{imageModel} is not a placeholder this launcher fills in".
- **Also in agent:** `test_reset_settings_sets_variable_once`, and for 34b `test_update_backs_up_before_first_start` and `test_rollback_restores_backup`.

## 5. Acceptance

The change crosses components, so acceptance runs on the boundary. Extend `c4-open-webui-acceptance.py`. It runs on GitHub's Windows and Ubuntu runners, on its own ports (never 8079-8083), with `EUGENE_PLEXUS_*` cleared.

1. The gateway has a stand-in SearXNG-shaped account and a stand-in image model.
2. Install the new pin. A chat with web search on gets links from the stand-in. The gateway attributes a `web_search` to the app's key. The stand-in's result pages were never fetched by Open WebUI.
3. An image request is answered by the stand-in through `/v1/images/generations`.
4. Start Open WebUI with no image model, then add one and press Reset. After one restart images work, and an earlier chat is still there.
5. For 34b, install the old pin and make a chat. Update: a backup exists and the chat is there. Make the new start fail with a bad variable. The page names the cause. Go back, and the earlier chat is back.
6. The drift script passes on the pin.

The row is not high risk, so no review is required. If one runs, it should attack the door as a way around a key's scope, and the file operations of Go back.

## 6. Do not change (other lanes' hot files)

- **gateway:**
  - `routes/inference.py` (rows 1, 55);
  - `routing.py`, `budget.py` (11, 14);
  - `server_tools.py` (56, 57, 59): import `SearchRunner`, do not edit it;
  - `metrics.py`, `decisions.py` (12);
  - `client_keys.py` (24, 40);
  - `door_paths.py` (58).
- **Exception: gateway `admission.py`.** Rows 11 and 40 own it. This row adds one line to `CLIENT_ADMISSION_PATHS`. Rebase onto row 11, and tell the orchestrator before landing.
- **agent:** `engines/*`, `runtimes.py` (13), `admission.py` (9). `client_doors.py` belongs to row 25, which is later in this lane.

## 7. Size, split, risks, calls

**Size M+, about 2.5 days.** Split:

- **34a, about 1.5 days:** the door, the entry, the placeholders, Reset, `ENABLE_PLUGINS` and the pin.
- **34b, about 1 day:** the backup, Go back, `resetsSettings` and the drift script.

Ship 34a and 34b in the same Edge build, so that existing installs reset once.

**Risks:**

- Open WebUI renames a variable. The drift script catches this.
- One shared app key throttles a busy install.
- The reset clears admin settings.

**Calls for Troy:**

1. **`ENABLE_PLUGINS`:** keep it on, and run Open WebUI only in an account of its own? Recommend yes.
2. **Google search accounts on this door:** skip them? Recommend skip, because of Google's display terms.
3. **The one reset at the update:** existing installs lose Open WebUI's admin settings once. Recommend accept it, with the Update button saying so.
4. **Images from an external, paid model:** allow, with a local model first? Recommend allow.
5. **Fetch result pages from Open WebUI's account?** Recommend no: use snippets only.

## Calls answered by Troy (2026-10-21)

- **OW-PLUGINS: Choice 1.** Plugins stay on.
- **OW-GOOGLE: Choice 2.** Open WebUI may use Google search. A search provider's terms are the account holder's to keep.
- **OW-RESET: Choice 1.** The Update button says the settings reset.
- **OW-IMAGES: Choice 1, and "local only" keys rule.** Keys already carry `limits.localOnly`; the gateway refuses every cloud backend for such a key. Open WebUI's key honours it as any key does.
