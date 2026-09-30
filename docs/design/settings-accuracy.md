# Settings that tell the truth about their value

**Status: built 2026-09-30, one session, on Troy's brief.** The rule, from
2026-09-29 and **fundamental**: *no settings widget anywhere in Eugene may show
a value other than the one in effect.* Found the day it was made: Amish_Station's
`updateChannel` had never been saved, the agent followed its alpha.5 install
(releases), and Settings showed **Edge** — an enum `<select>` with `value=""`
matches no option, and a browser shows the first one. ui `2f7b924` added a "Not
set" option; that was a patch. This is the audit of every setting on every
surface, and the fix for each.

Run record: [`docs/acceptance/settings-accuracy-run.md`](../acceptance/settings-accuracy-run.md).

## Decisions

Every call below was taken by this session and is **Troy's to overturn**, except
the ones marked *Troy* (his, in the brief or in answer to a question this
session asked because it touched security).

| # | The call | Taken | Why |
| - | -------- | ----- | --- |
| **1** | `updateChannel`: unset and inference, or a default? | **A default: `releases`** (*Troy*). A binary choice with no "unset". | An unset value was a guess re-made at every check, and the widget could not show a guess. |
| **2** | How does no existing install change channel? | **Settled once.** A file that never saved a channel keeps the one it followed: a **container's** from its image tag, at load; a **native** install's by its first update check that can read the release list (it depends on whether its commits are a recent release, which only the network can say). Until then the channel is **`pending`** and says so — no guess is shown, nothing is offered. A marker beside `agent.yaml` (`.update-channel-settled`, the gateway's `defaultMaxTokens` pattern) keeps a later reset a reset. | A migration that writes a guess at boot would be wrong for an offline release install; one that waits is honest about the wait. |
| **3** | And `infer_channel`? | **Gone as a runtime rule.** The old logic survives as `channel_before_default`, called only by that one settling. | *Troy*: remove inference. It cannot be deleted outright while installs exist that have not settled. |
| **4** | An older build offered as an update? | **Never.** Each component whose commit differs is placed by its **commit date** (GitHub's git-data endpoint, cached for the process): `behind` or `ahead`. `available` = something behind and nothing ahead. A part the target predates (the tool-driver, before P8) is `ahead`. Same-second different commits count as ahead. `POST /v1/node/update` refuses a downgrade, and a result for another channel is set aside. | `behind()` compared with `!=`, so an install from `main` following releases — or one installed from a commit whose checks were still running — was told alpha.5 was "A newer version". Dates, not `compare`: a comparison carries every changed file and grows with the distance. |
| **5** | The `:edge` container's default | **`edge`, from the image** (*Troy*): `EUGENE_PLEXUS_AGENT_DEFAULT_UPDATE_CHANNEL`, set by the Dockerfile from `EP_UPDATE_CHANNEL` (`releases` for a release tag). Shown as the default with its source; never written to the file. | The library's `EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS` pattern. A pulled release image changes the default with it. |
| **6** | A new native install from `main` | **Follows releases** (the default), and is told it is **newer than the newest release** rather than offered one. Not changed: the installers are the same bytes on `main` and in a release, so they cannot tell. | Rule 2 makes the state honest; a `--channel` for the installer is a follow-up if Troy wants it. |
| **7** | Secret presence (keys, share logins) | **Reported, never the value** (*Troy*, asked). Share-login rows carry `hasPassword`; a provider key taken from the environment reads "Not set here: uses the OPENAI_API_KEY in this machine's environment". The contract's "`<redacted>` regardless of whether set" was false of every component and is corrected. | Every row read "saved"; an env key read "Not set" while in use. |
| **8** | Driver address fields shown for every provider that reads them | **Shown** (*Troy*, asked), with "Not set: uses OpenRouter's own address, https://openrouter.ai/api". Not changed: which providers read them. | A stale `baseUrl`, invisible on the page, sent an account's key to it. |
| **9** | `securityMode` (agent and control) | **Not `requiresRestart`**, plus a warning when the chosen mode cannot work here (*Troy*, asked). | Nothing restarts: the keyring entry is stored/removed at save time. Control restarted itself after every change and came back locked in prompt mode. |
| **10** | CORS and bind display | **Say what is in effect** (*Troy*, asked): an empty `corsAllowedOrigins` is "any website"; an unset `advertiseUrl` names the derived address and that the agent's own socket needs a restart. Display only. | "Default: none", and the standby list's sentence, under the gateway's origins. |
| **11** | A value the widget cannot show | **Shown as itself, with why**: an enum value not in the list is its own selected option ("\"beta\" (not one of the choices)"); a checkbox holding a non-boolean is half-set; a number box never goes blank over a string. | A widget that coerces a value to one it can show is showing a choice nobody made. |
| **12** | A `null` in a component's file for a field with a default | **The default**, in every component, as a PATCH of null already was. | `metricsEnabled: null` turned metrics off, `catalogueEnabled: null` the catalogue, `probeMinutes: null` the probe — while GET said null and the schema said on. |
| **13** | `requiresRestart` results | **Per PATCH, and only while the value differs from what runs.** The schema reports each pending field (`pendingRestart`, `inEffect`). | The gateway, library and both drivers returned every restart key saved since start, so a later save of a live field restarted the process. |
| **14** | Keys the agent manages on a companion driver | **Read-only** (`managedBy`) and **refused by PATCH**. The agent names them to the driver at spawn (`EUGENE_PLEXUS_DRIVER_MANAGED_KEYS`), once for an existing companion. | An edit stuck until the agent's next start rewrote it. |
| **15** | Legacy stored defaults (`requestTimeoutSeconds: 180` from before 2026-09-18) | **Left alone.** | Not a lie: 180 is shown and 180 is in effect. Clearing it changes behaviour. Recorded. |
| **16** | Profile flags | **Unset is not the schema default.** The editor filled every blank box with the adapter's default, so a profile read as setting values it did not; the adapter's stated default is now a sentence attributed to it. | The agent passes nothing for an unset flag. |

## The contract (specs `c9098f7` + `7dcae2a`)

`ConfigField` gained six optional properties, each so a widget can say what is
in effect without per-component UI code:

| Property | Means | First users |
| -------- | ----- | ----------- |
| `defaultSource` | Where `default` comes from when it is not built in. | agent `updateChannel` (the image), library `modelRoots` (the environment) |
| `unsetMeans` | What the field does while it holds no value — for a list, while empty. May be computed per request. | gateway `defaultMaxTokens`, `corsAllowedOrigins`, `controlUrl`; driver `baseUrl`, `apiKey`, `modelId`; agent engine paths; control `standbyUrls` |
| `unsetResolvesTo` | The value an unset field stands for right now. Never for a secret. | driver `baseUrl`, gateway `controlUrl`, agent `advertiseUrl`, `vllmBinary` |
| `pendingRestart` + `inEffect` | Saved, not in effect; what runs meanwhile. | gateway, library, control, both drivers |
| `managedBy` | Written by another part of the install; read-only. | companion drivers' five managed keys |
| `status` (`ConfigFieldStatus`, level named `ConfigFieldStatusLevel`) | What the value is doing now when the value alone does not say. | `securityMode` (agent, control), `advertiseUrl`, `modelCopyDir` |

`ConfigDocument` now says a sensitive field reads `"<redacted>"` only when it
holds a value; `ShareCredential.hasPassword`; `NodeUpdate.ahead`, `channel`
absent while `pending`, `UpdateChannelSource` gains `default` and `pending`
(`inferred` kept for agents before this change). `showWhen` must cover every
provider that reads a field, and is evaluated on the controller's effective
value.

## Inventory: every setting

Verdicts: **(a)** a closed choice given a real default; **(b)** unset means
something, and the widget says what; **(c)** derived, inherited, redacted,
pending or managed, shown with its source; **—** already truthful, no change.

### Agent (20 fields)

| Key | Type | Unset today | Widget showed | Verdict | Fix |
| --- | ---- | ----------- | ------------- | ------- | --- |
| `firstRunComplete` | bool | false | hidden | — | hidden everywhere (the wizard's flag) |
| `securityMode` | enum | prompt | "restart required"; a mode that cannot work here as if it did | (c) | not `requiresRestart`; `status` warns (no passphrase file, keyring refuses) or informs (file written at next sign-in) |
| `uiTheme`, `uiFontSize` | enum | nothing reads them | hidden | — | still hidden; deleting them is a follow-up |
| `engineBinaryRoots` | path_list | [] | "No directories yet. Point this at wherever you keep models" | (b) | generic "None." — the models sentence was wrong for engine directories |
| `allowUnrestrictedEngineLaunch` | bool | false | — | — | — |
| `vllmBinary`, `mlxBinary` | file_path | PATH lookup | empty box | (b) | "Not set: uses the `vllm` found on PATH (…)", or that none is |
| `uvBinary` | file_path | beside the install, else PATH | empty box | (b) | names the uv found |
| `allowCustomApps` | bool | false | — | — | (not checked by `/start` — recorded, not a widget) |
| `kevPython` | file_path | Kev reads as not installed | empty box | (b) | says so, and why PATH is not searched |
| `advertiseUrl` | url | derived from the route to the root | empty box | (b)/(c) | the derived address as `unsetResolvesTo`; `status` when the agent's own socket still needs a restart |
| `allowedHosts` | string | "" | — | — | — |
| `pathMappings` | path_mappings | [] | junk rows dropped silently | (c) | counted and said |
| `shareCredentials` | share_credentials | [] | every row "saved"; `null` refused | (c) | `hasPassword` per row; `null` is the default |
| `modelCopyEnabled`, `modelCopyMinFreeGb` | bool, int | false, 50 | — | — | — |
| `modelCopyDir` | file_path | nothing is copied | empty box | (b) | says so; `status` when copying is on with no folder |
| `updateChecks` | bool | true | description claimed "never asks GitHub" | — | description corrected (Check now asks); re-enabling checks within a minute |
| `updateChannel` | enum | inferred at every check | **Edge** for an unset value | (a) | decisions 1-5 |

A `null` in `agent.yaml` for a defaulted field is the default (decision 12).

### Gateway (21 fields)

| Key | Unset today | Widget showed | Verdict | Fix |
| --- | ----------- | ------------- | ------- | --- |
| `defaultTemperature` | 0.7; a file `null` sent none | null | — / 12 | file null is the default |
| `defaultMaxTokens` | no cap | blank box | (b) | "No cap: an answer runs until the model finishes…" |
| `maxToolCalls`, `decisionMaxQuestions`, `maxImagesPerRequest`, `profile*Seconds`, `swapWaitSeconds`, `idleCheckSeconds` | their defaults | — | — | out-of-range file values now shown with the range |
| `imageToolModel` | the app's model, else the key's one image model | blank | (b) | says so |
| `requestTimeoutSeconds` | 600 (180 on installs before 2026-09-18) | — | — | NaN refused; Test's fallback is 600, not 30; decision 15 |
| `routingRefreshSeconds` | 15, **captured at start** | the new value while the old was in effect | (c) | read at every sleep |
| `modelSlots` | none | summary | (b) | "None: each model is served only by its own backends" |
| `loadBalancing`, `corsEnabled` | their defaults | — | — | — |
| `controlUrl` | found through the agent | "(off)" | (b) | "Not set" + the address the last refresh found |
| `logLevel`, `metricsEnabled`, `metricsRollupEnabled` | defaults; file nulls turned metrics off | restart result cumulative | (c) / 12 | per-PATCH restart; pending shown; file null is the default |
| `metricsRetentionDays` | **0 ran as 7** | 0 | (c) | 0 is 0 (keep no individual requests) |
| `corsAllowedOrigins` | any origin | "Default: none", and the standby sentence | (b) | "Empty: any website may call…" |

### Library (11 fields)

| Key | Verdict | Fix |
| --- | ------- | --- |
| `modelRoots` | (c) | `defaultSource` names the environment; empty list says nothing is scanned |
| `scanOnStartup`, `catalogueEnabled` | 12 | file null is the default |
| `followSymlinks`, `downloadLayout`, `maxConcurrentDownloads`, `guidanceContextLength`, `logLevel` | — | per-PATCH restart; pending shown |
| `catalogueBaseUrl` | (b) | "" is the hub (was stored and shown as "") |
| `hfToken` | (c) | "" is no token (it read `"<redacted>"`); unset says the hub is asked anonymously; a saved token reaches downloads at once |
| `starterModelsFile` | (b) | "Not set: uses the starter list shipped with this version" |

### Control root (9 fields)

| Key | Verdict | Fix |
| --- | ------- | --- |
| `securityMode` | (c) | not `requiresRestart` (decision 9); `status` for an authorized caller only — an anonymous schema read gets the shape alone |
| `standbyUrls` | (b) | "No standbys…" in control's own words (the UI borrowed them for every URL list) |
| `nodePollIntervalSeconds`, `joinTokenTtlSeconds` | — | — |
| `nodeRequestTimeoutSeconds` | — | NaN refused |
| `logLevel` | (c) | pending shown with the level the root logger runs at |
| `firstRunComplete`, `uiTheme`, `uiFontSize` | — | hidden; nothing reads them |

### Inference driver (17 fields)

| Key | Verdict | Fix |
| --- | ------- | --- |
| `provider` | (c) | managed on a companion; pending shown; `/v1/info` names the provider running, not the one saved |
| `baseUrl`, `runtimeName` | (b), decision 8 | shown for every provider that reads them; the provider's own address named |
| `apiKey` | (c), decision 7 | shown for TypeSafe (which needs one); env key named; "" is no key |
| `catalogueRefreshMinutes` | — | shown for ElevenLabs, which reads it |
| `modelId`, `upstreamModelId` | (b) | per provider: every model the account lists; the CLI's default; `kev-latest`; "the same as the model id". Hidden for ElevenLabs, which reads neither |
| `thinkingMode` | — | hidden where nothing reads it |
| `backendLocality` | — | shown only where it is honoured |
| `decisionMaxConcurrent` | (b) | "no limit is advertised" |
| `streamStallSeconds`, `requestTimeoutSeconds`, `logLevel`, `catalogueInclude/Exclude`, CLI paths | — | per-PATCH restart; NaN refused |

### Tool driver (9 fields)

`baseUrl` (b): SearXNG searches nothing without it; Brave's own address named.
`language` (b). `apiKey` (c): "" is no key. `probeMinutes`: file null is the
default (was 0, probe off). Per-PATCH restart; NaN refused.

### The UI's own preferences

Theme and font size (browser storage): the default is labelled, and **System
says what it resolves to now**.

## Inventory: the special editors

| Surface | What it showed | Fix |
| ------- | -------------- | --- |
| Settings page (`/config`) | `showWhen` decided once from the first read; a stale cached read after a save elsewhere | re-reads after any write; every write empties the cache |
| Config editor save | a read-back failure after a successful save said "Could not save" | its own line: saved, could not be read back |
| Versions / Issues | "A newer version is ready" about an older one; the channel's guess; "did not answer" while loading; a three-week-old failure | newer only from an agent that can say; ahead / mixed / undecided states; "Reading…"; the same week everywhere |
| Client key limits | a key allowed `["web_search"]` read as not allowed; an emptied box stored 0; a legacy key's editor showed defaults as its values; an unreadable list read "none yet" | all four |
| Profiles | unset flags showed the adapter default as a value, clearing snapped back; an engine not offered showed the first engine; "Use fallback" named no fallback; stored values on a non-default profile read as in use | all four |
| Folders | an override spelled differently read "inherits"; overrides that could not be read could be saved over | both |
| Share logins | "saved" for every row | `hasPassword` |
| Reach card | "restart before  starts working" with no address | says there is no address yet |
| Playground sampling | placeholders 0.7 / 1024 / 0.9 / 42 read as defaults | "not set" |
| Routing | "its own backends" with no routing table | says it cannot see which |
| Appearance | a never-chosen theme looked chosen; System said nothing | default labelled; System's current theme named |

## Found, not fixed (recorded, each its own call)

- **Safe mode overwrites the whole config file on the next PATCH** (agent,
  gateway, library): the file is not loaded, so a save writes defaults plus the
  patch — for the agent, `components: []`, `runtimes: []` and no `auth` block.
  A data-loss defect, not a widget; wants a merge-on-write in safe mode.
- **`OPENAI_API_KEY` in the agent's environment reaches every driver**, and the
  OpenAI-compatible engine sends it as a bearer even to local runtimes and
  custom URLs. A security behaviour, deliberately not changed here.
- **Control's standby status reports every standby unreachable**:
  `standby_reports` is initialised and never written. A status surface, not a
  setting; its field description promises a lag report that cannot exist.
- **`allowCustomApps` off does not stop an installed custom app starting**
  (`/start` and the boot start do not check it).
- **No component validates its config file at load** beyond nulls: a string
  `"false"` for a boolean reads true in several readers. The widgets now show
  such a value as one they cannot show; the readers are unchanged.
- **The component-URL dropdown on a machine's section reads the local
  agent's topology**, and a backend's Settings page targets its driver by bare
  name. Low: two same-named drivers on two machines is the only case.
- **A remembered node that has left the install** silently falls back to this
  machine in the node picker; the picker shows the node actually selected.
- **The installers cannot say which channel they were run for** (decision 6).
