# Eugene Plexus changelog

Cross-component release notes. Each repo has its own commit history; this file consolidates what shipped together.

---

## Unreleased — local-LLM-training platform (v0.3 direction)

Direction change: Eugene Plexus expands into a full-stack, UI-driven platform for local LLM training, evaluation, and inference. This first spec PR introduces the `TrainingProject` abstraction and the contracts for six new components. Schemas only — no implementation yet. Contracts are drafted upfront (not incrementally) so they don't conflict at integration time; implementation lands later, starting with `data` + `trainer`.

### specs

- **`ComponentKind` extended** with `coordinator`, `trainer`, `data`, `eval`, `inference`, `cluster`.
- **New shared schemas in `common.yaml`** — the `TrainingProject` family (`TrainingProject`, `TrainingGoal`, `ModelTemplate`, `ArchitectureConfig`, `TrainingRecipe`, `Hyperparameters`, `HardwareTopology`, `TrainingRun`, `RunStatus`, `TrainingMetricPoint`, `Checkpoint`, `CheckpointRef`, `DatasetRef`, `TokenizerRef`, `EvalSuiteRef`, `ExportSettings`) plus the coordinator pipeline + hand-off schemas (`PipelineRun`, `PipelineStage`, `PipelineStatus`, `TrainingRunRequest`).
- **New spec files** — full `coordinator.yaml` (owns the `TrainingProject` aggregate and sequences pipeline runs across components) and `training.yaml` (executes training runs, owns checkpoints); thin `data.yaml` / `eval.yaml` / `inference.yaml` stubs; deferred `cluster.yaml` placeholder (multi-host, post single-host milestone).
- **Component ports** — coordinator 8086, trainer 8087, data 8088, eval 8089, inference 8090, cluster 8091.
- **CI** — the six new top-level specs are added to the Redocly lint set.

---

## v0.2.0 — 2026-05-25 (shipping; pending tag)

The "Eugene gains agency" release. v0.1 was a working bicameral loop with a thin shared system prompt and no persistence. v0.2 turns Eugene into a multi-component organism: a stored identity that survives restarts, person-keyed memory, drives-and-NT modulation of the deliberation loop, and a first external sense organ (the Discord-aware `connector`). Late in the cycle, three architectural fixes to the user-facing reply path raised the practical persona ceiling further than any of the v0.2 features could have on their own.

Eight repos under `github.com/eugene-plexus`: `specs`, `orchestrator`, `hemisphere-driver`, `ui`, `watchdog`, `memory`, plus the new `identity` and `connector`.

### Security

A complete identity-and-secret arc grafted on top of v0.1's anonymous LAN-only assumption.

- **Argon2id passphrase + master-key derivation.** First-run wizard takes an operator passphrase, derives a master key via Argon2id, stashes salt + verifier on the watchdog. Subsequent boots prompt, re-derive, hold the master key in memory only.
- **OS keyring auto-unlock** (opt-in). Switch `securityMode` to `os_keyring` and the master key persists to the system keyring so Eugene boots unattended. Passphrase still works if the keyring is unavailable.
- **libsodium secretbox at-rest encryption** for sensitive config fields (`apiKey`, `botToken`). Plaintext is never written to YAML once a master key exists.
- **JWT bearer auth across all components.** Watchdog mints session tokens for the operator and service tokens for inter-component calls. Every body component verifies against the shared signing key without holding the secret itself.
- **Restart-on-login**: when the operator first sets up, the watchdog restarts supervised children so they all receive the freshly-derived master key as an env var.
- **`/login` page + session management** in the UI. Pre-init probe so the unlock vs. set-passphrase screen doesn't flash the wrong copy. Sign-out revokes server-side.

### New component: `identity`

A "default mode network" for Eugene — the constitution + self-model + relationship layer that the orchestrator consults before every chat turn.

- **Constitution** — declarative facts (name, pronouns, core values, free-text).
- **Self-model** — patterns Eugene notices about himself over time. Manually editable; reflection populates programmatically.
- **Persons** — people Eugene knows. One operator (you) is created at first run; others land via the pending-link flow from the connector.
- **Platform aliases** — `{platform, accountId}` pairs mapping external chat-platform users to a `personId`. Spoof resistance lives here.
- **Pending identity links** — unknown platform users → adapter files a pending link, replies "ask the operator to authorize," STOPS. No orchestrator call until the operator approves.
- **Reflection backend** — `POST /v1/identity/self-model/reflect` reads recent memory turns, asks a hemisphere driver to extract self-model observations, persists them. End-to-end shipped; NT-driven autonomy is v0.3.

### Memory upgrades

- **Person-keyed entries.** Every turn carries `personId` of who said it. Global timeline + per-person retrieval. Both ends of a chat turn (user message + Eugene's reply) are now full `MemoryEntry` objects with personId + NT snapshot + hemisphere attribution.
- **Backend registry.** `backend: local_sqlite` (default, durable) and `backend: in_process` (volatile, for tests / short-lived experiments). Schema is the same; storage is pluggable.
- **Recent-turns context** — orchestrator pulls recent turns with the speaker on every chat turn and injects them into per-hemisphere prompts as concrete relationship context.
- **Search wire-stub** — endpoint accepts the request shape and returns 503; sentence-transformers backend lands in v0.3.

### NT system (drives-and-modulation)

Eugene now has internal state that evolves across turns and modulates the bicameral loop.

- **Live state** — per-NT `{level, baseline, decay}` shape on `NTState`. Persisted snapshot lives on every memory entry so future analyses can correlate output style against state.
- **Observation impulses** — final-pass agreement, pass count, average pass latency feed back into NT state at end of each turn.
- **Modulated `max_passes`** — anxious / alert Eugene gets more deliberation passes; calm Eugene short-circuits.
- **Modulated `temperature`** — dopamine / GABA stretch or compress per-pass temperature.

Modulation is live but parameter tuning is empirical; expect shifts in v0.3 as we get real operator observation data.

### New component: `connector` + Discord adapter

The first external sense organ. Bridges Discord (today; Slack/Matrix/Telegram/Gmail in v0.3+) to Eugene's chat surface.

- **Adapter registry** — one connector process can host multiple platform adapters. Adding a kind is one class implementing the `Adapter` protocol; the UI's `ConnectorPanel` discovers each adapter's config schema at runtime via `GET /v1/adapters/{name}/config/schema` and renders it with the same machinery as the rest of the UI.
- **Discord adapter** — DMs always honored; `@<bot>` mentions in operator-allowlisted channels. Channel-context lookback (last N messages before the mention) goes to the orchestrator as prompt-side context, NOT persisted to memory.
- **Pending-link flow** — unknown Discord users → adapter files a `PendingIdentityLink` on identity, replies "ask the operator to authorize this link" on the platform, STOP. Spoof-resistant by construction.
- **Operator runbook** at [`connector/docs/discord-setup.md`](https://github.com/eugene-plexus/connector/blob/main/docs/discord-setup.md) — 10-section end-to-end walkthrough from "I have a running install" to "Eugene replies to my DMs."

### Persona ceiling (v0.2.x architectural fixes)

A late-cycle empirical finding: the bicameral architecture's persona ceiling was limited not by which models were in the hemispheres but by how the user-facing reply got produced. Three changes lifted the practical ceiling substantially.

- **Voice pass** — a single post-deliberation LLM call that converts the inner-dialog register of the hemispheres into a user-facing reply. The hemispheres' raw outputs become diagnostic artifacts; the voice pass output IS the user-facing message. `voiceDriver` is operator-configurable (defaults to first driver). The voice driver choice is empirically the **persona lever** — same hemispheres, only the voice driver swapped, takes user-facing output from helpful-assistant to short/dismissive/in-character.
- **Scratchpad structure** — deliberation summary lives in the voice pass's system message as private notes the model can't address, not as a trailing user-role message. The prior structure made the model address the deliberation back at the user, producing "you just narrated my internal monologue back at me"-shaped responses.
- **Social-context directive** — voice pass directive includes explicit anti-helpful-assistant language ("if the message is confusing, weird, or a strange opener, react to THAT, briefly. Don't explain, don't catalog, don't lecture."). Real-person-like reactions to unusual openers are now reachable.
- **Embedding-based agreement scoring** — Jaccard word-overlap replaced with sentence-transformer cosine similarity (`all-MiniLM-L6-v2` default, operator-configurable). Two responses meaning the same thing in different words now score 0.7-0.85 instead of 0.05-0.15; the loop terminates at the actual point of substantive agreement instead of grinding to `cap_reached`. `agreementThreshold` default bumped 0.5 → 0.75 to match the embedding cosine scale.
- **Thicker `DEFAULT_SYSTEM_PROMPT`** — explicit `Format requirements:` (first person, no speaker labels, no script format, one contiguous response) ahead of `Character:`. Anti-script directives are no-ops for commercial models and load-bearing for less-RLHF'd models. Side effect: commercial models also produce tighter defensive responses with the thicker prompt.

Net effect: where v0.1 produced a polished essay for *every* prompt, v0.2.x produces "What? I don't know what that's supposed to mean. Are you quoting something?" to a weird opener and "I like some of it — mostly the older stuff. Miles Davis, John Coltrane — that era" to a normal one. Both registers from the same baseline.

### First-run wizard

Linear 10-screen flow (v0.1 had 7; v0.2 inserted Security, then split Memory / Identity / Connector out of one screen):

1. Look & feel — local theme + font, live preview
2. **Security** (new) — passphrase + securityMode
3. Welcome — plain-language "body parts" framing
4. Deployment — all-local vs. networked
5. Orchestrator host:port (networked only)
6. Driver 1 — provider + credential + model
7. Driver 2 — same with a "pick a different vendor" hint
8. **Memory** (new screen) — backend choice + path
9. **Identity** (new screen) — display name override + reflection wiring
10. **Connectors + Start** (new screen) — Discord opt-in, summary, Start

Transactional commit: the wizard treats the whole flow as one transaction. Initialize → security mode → driver configs → memory → identity → orchestrator's `identityUrl` → connector adapter → `firstRunComplete: true` → restart everything that picked up new config.

A visual progress bar in the wizard header animates fill width across screen transitions.

### UI polish

- **Combobox for `suggestions`-bearing string fields.** The new `ConfigField.suggestions` spec field lets backends emit advisory dropdowns alongside free-text input. `modelId` (live model list from the driver) and `voiceDriver` (configured driver topology) both use this. Operators pick from a dropdown OR paste an id the backend doesn't know about yet (just-pulled Ollama model, just-deployed custom endpoint) — validation accepts either.
- **Auto-restart on save.** When a config patch requires a restart, `ConfigEditor.save()` triggers `performRestart()` directly. The "restart now? / later" confirmation modal is gone. The progress modal still surfaces and the success phase auto-dismisses after 1.5s. Click count for a restart-required change went from 5+ to 2.
- **Theme-aware status banner CSS.** Modern light theme is now readable — previous amber/rose/emerald palette was dark-theme-only. `--status-{success,warn,error}-{fg,bg,border}` variables drive `.status-*` and `.text-status-*` utility classes.
- **`CopyTraceButton`** — diagnostic component that copies the full bicameral trace of the most recent turn as Markdown (user prompt + per-pass inputs/outputs + voice pass input/output + final response). Pastes cleanly into a Claude follow-up or a GitHub issue.
- **`ConnectorPanel`** — Settings + Adapters sub-tabs in `/config`. Add / configure / test / delete adapters with schema-driven editor. v0.3+ adapter kinds drop in without UI changes.
- **Error clearing on user action** — ConfigEditor and ConnectorPanel clear last test/save status on any field edit, preventing stale "test failed" banners from persisting next to successful saves.

### Hemisphere-driver

- **`thinkingMode` config field** (auto / off / low / medium / high). Controls reasoning-block emission for thinking models (MiniMax-M2, DeepSeek). `off` appends an anti-reasoning system-prompt directive AND strips `<think>...</think>` blocks post-response. Solved cases where reasoning leaked into the user-facing chat surface.
- **At-rest encryption for sensitive fields** (`apiKey`) — libsodium secretbox envelopes, plaintext never written to disk once a master key exists.
- **Local providers don't require API keys.** Ollama + LM Studio adapters set `auth_required: false`; engine no longer rejects construction on a blank `apiKey` for these. Bearer header is omitted from outbound calls when the key is empty.
- **Local providers don't filter the model list.** The chat-prefix heuristic stays on for OpenAI (filters out embeddings / audio / image models) but is off for local servers that list ONLY what the operator pulled.
- **`modelId` carries suggestions instead of a strict enum.** The discovered model list is advisory; the operator can paste a just-pulled id without losing it to validation.

### Spec additions

- `ConfigField.suggestions: string[]` — advisory discovery hints; UIs render as combobox.
- `ConfigField.componentKindHint: ComponentKind` — declarative "this field points at a peer component of this kind"; UI renders kind-hinted fields as dropdowns sourced from the watchdog topology with `(off)` as the first option. Stops operators from copy-pasting URLs they shouldn't need to know.
- `ComponentKind` relocated from `watchdog.yaml` to `common.yaml` — multiple components now reference it (watchdog directly, anyone using `componentKindHint` indirectly).
- `PassRecord.hemisphereInputs: HemisphereInput[]` — per-driver input snapshots for diagnostic traces.
- `VoicePassRecord` + `ChatResponse.voicePass` — voice-pass driver name, input messages, output, latency.
- `Health.safeMode: bool` — uniform safe-mode reporting across components.
- `ComponentKind.identity` + `ComponentKind.connector` — watchdog topology kinds for the new components.
- Full v0.2 entity set: `Constitution`, `SelfModelEntry`, `Person`, `PlatformAlias`, `PendingIdentityLink`, `RelationshipSummary`, `MemoryEntry`, `MemorySearchRequest/Result/Hit`, `MemoryBackendKind`, `AdapterEntry`, `AdapterKind`, `MessageSource`, `ChannelContextEntry`, `MasterKeyEnvelope`, `SecurityMode`, `AuthLoginRequest/Response`.
- New v0.2 `NTState` shape — per-NT `{level, baseline, decay}` + `lastUpdated`.

### Fixes

- **Proxy trailing-slash bug** — watchdog topology URLs arrive with a trailing slash; naive concatenation produced double-slash paths that FastAPI 404'd. Affected Memory / Identity / Connector config tabs. Normalized in the proxy.
- **Chat page auth gate** — probes `/v1/auth/status` (public endpoint, no auth cost) before any `/v1/config` call so the auto-redirect-on-401 path can't bounce a fresh install through `/login` on its way to `/setup`.
- **Proxy auth threading** — incoming `Authorization` header forwarded to the resolver so per-driver `/v1/config` lookups don't 401 when the orchestrator's resolve path needs auth.
- **`<think>` block leaks** — thinking-mode `off` strips them with a post-response regex pass even when the upstream chat template ignores the prompt directive.

### Late hardening (post-smoke-test, 2026-05-25)

Items surfaced during the v0.2 smoke test and fixed before the tag.

- **Identity startup deadlock (release blocker).** `IdentityStore.ensure_operator()` held a non-reentrant `threading.Lock` while calling `get_person()`, which tried to re-acquire it. First boot worked (no row → fell through to the lock-released `create_person` path); every subsequent boot deadlocked silently — no traceback, no crash counter. Fixed by closing the `with self._lock:` block before the cross-call. Regression test runs the second `ensure_operator()` on a background thread with a 5s join-timeout, so a future re-introduction fails an assertion instead of hanging the suite.
- **Identity lifespan diagnostics.** Each step inside the lifespan now emits a `log.info("lifespan: <step>")` checkpoint and is wrapped in `asyncio.wait_for(..., timeout=30s)`. Future silent stalls surface as `TimeoutError` tracebacks with the exact step pinpointed. `logging.basicConfig(level=INFO)` added in `__main__.py` so the checkpoints actually reach stdout (uvicorn's `log_level=` only touches `uvicorn.*` loggers).
- **Reflection peer URLs require restart to take effect.** `reflectionHemisphereUrl` / `reflectionMemoryUrl` were missing `requiresRestart=True`. The cached `hemisphere_client` / `memory_client` are built once in the lifespan; PATCH'd URLs didn't change runtime behavior until restart. UI auto-restart-on-save now triggers correctly.
- **Watchdog supervisor pipes + prefixes child output.** Children inherited the parent terminal, so concurrent boots produced an unlabeled wall of `INFO: Waiting for application startup` with no source identification. Supervisor now PIPEs each child's stdout (with stderr merged), spawns a reader task per child, and re-emits lines as `[<name>] <line>`. Drivers (which can be named arbitrarily by operators) get the disambiguated prefix `[driver: <name>]` so a renamed driver is unmistakable.
- **Watchdog log signal-to-noise.** 2xx `/healthz` access logs (~24 lines/min across the body) are suppressed at the reader; non-2xx pass through so a newly-unhealthy component is still visible. `error` / `warning` words get ANSI color (red/yellow, word-only — full-line color is unreadable on dark terminals); honors `NO_COLOR` env var as the documented opt-out.
- **Watchdog rotating-file log capture.** `sys.stdout` / `sys.stderr` are mirrored to `<watchdog.yaml dir>/logs/watchdog.log` (10 MB × 5 backups = 50 MB cap). Operators get a sharable bug-report artifact without redirecting stdout at task-launch time or learning env vars; GUI-equality principle.
- **Peer-reference dropdowns end-to-end** (the `componentKindHint` rollout above). The 7 fields that adopted it: `identity.reflectionHemisphereUrl`, `identity.reflectionMemoryUrl`, `orchestrator.memoryUrl`, `orchestrator.identityUrl`, `orchestrator.drivers[].url` (per-row dropdown inside the driver list), `connector.orchestratorUrl`, `connector.identityUrl`. Wire shape unchanged — the hint only changes the input UX. Closes the OpenClaw trap of duplicating watchdog topology into per-component free-text URL fields.
- **`basicConfig` logging across all body components.** Identity / orchestrator / hemisphere-driver / memory / connector were emitting warnings without timestamps because uvicorn's `--log-level` only touches `uvicorn.*` loggers. Added `logging.basicConfig(level=INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)` in each component's `__main__.py` before `uvicorn.run`. Stale "encrypted on disk, no master key available" warnings are now distinguishable from current ones at a glance — surfaced by a smoke-test session where the operator couldn't tell whether the warning was from the failed save five minutes ago or the successful one thirty seconds ago.
- **Auto-engage safe mode after repeated crashes.** Watchdog supervisor flips a component to safe-mode after `autoSafeModeAfterCrashes` (default 5) consecutive crashes, and gives up entirely after twice that (default 10). Closes the "config edit soft-bricks the install" failure mode without needing operator intervention — paired with the GUI-equality principle (operator never needs to set an env var to recover). `restart()` clears the auto-engaged flag so the operator can re-test after the fix.
- **`POST /v1/config/test` on the watchdog.** Probes an OS keyring round-trip when `securityMode=os_keyring` (or under explicit override). UI Test button on the Watchdog tab now has something to talk to — was 404 before. Lets operators verify keyring access works before relying on auto-unlock at next boot.
- **`personRecentLimit` default bumped 10 → 30.** Smoke-test caught Eugene confabulating personal history because the recent-turns slice for the speaker was too short — the relevant prior turn had aged out of context. Bumping to 30 fixes the confabulation without measurable latency cost (the slice is system-prompt material, not user-input length).
- **Discord adapter UX fixes.** Pending-link reply reworded from "ask the operator to authorize this link" (ambiguous — sounded like it referred to the Discord connector itself, not the speaker's identity) to point explicitly at the Identity → Pending screen. Typing indicator wraps the orchestrator call so users see Eugene is "thinking" while passes run. Orchestrator-side failures now send a Discord fallback message including the exception class — previously a 502 fell silently through `on_message`'s try/except and the Discord user got nothing.
- **`ConnectorPanel` polls while transient.** After adapter save, panel polls `/v1/adapters` at 1.5s while any adapter is in `starting` or `rate_limited`. Previous one-shot reload raced the adapter's background task and left the UI saying "launching" until the next manual refresh, even when the adapter had already errored out.

### Late UI polish (post-smoke-test, 2026-05-25)

- **"Thought for X.Xs ›" chip.** ChatGPT-style chip rendered above the latest Eugene response showing total turn latency. Click expands to show pass count, agreement score, termination decision, voice driver, and per-pass mini-summary. Makes bicameral pass behavior legible without opening DevTools or pulling the trace via `CopyTraceButton`.
- **Watchdog tab on the Config page.** Closes the gap where the watchdog had a config endpoint but no UI tab. `Test` button drives the new `POST /v1/config/test` for keyring round-trip verification.
- **Pre-render auth gate.** Chat page checks `hasSessionToken()` before any authed call and redirects to `/login?next=...` if missing — the underlying page no longer paints first when an unauthenticated user arrives, which had been a small security smell (operator UI flash before the login modal popped). Catch path distinguishes `ApiError(401)` (stays in "checking" until the redirect completes) from other errors so the redirect can't be raced.
- **`--radius` theme token.** Bubble / badge / button / pass-card / modal / form-field switched from `rounded-md` to `rounded-[var(--radius)]` so themes can pick their own corner radius without per-component overrides. 118 swaps across 15 files. `rounded-full` (pills, dots, scrollbar) is intentionally untouched. `--pad` token added alongside for density tuning (declared per theme; not yet wired into spacing utilities — v0.3).

### Three themes (Cyberpunk / Modern / Editorial)

The token framework introduced by `--radius` + `--pad` paid off immediately: Claude Design produced three theme presets that each compose into roughly 50 lines of CSS without touching component code. Validates that the token framework holds up cleanly for new themes.

- **Cyberpunk** — Miami '26 palette (replaces the prior v0.2 cyberpunk colors). Dark violet (#0c0820) base, teal + pink accents (#1bd9c2 / #ff7ac0), Space Grotesk + JetBrains Mono. 4px corners, bubble blur, perimeter-pulse thinking animation. Default theme.
- **Modern** — light theme refresh. Near-white (#fafafb) base, deep blue + magenta accents (#2a55e6 / #cf3a85), Inter + JetBrains Mono, 6px corners, spinner-rail thinking state.
- **Editorial** (new third theme) — newsprint cream (#faf7f1) base, forest green + rust accents (#2d6240 / #a23b29), DM Sans throughout, 6px corners, no bubble blur, no Eugene letterform showing through the chrome.

`system` theme resolves to Cyberpunk (dark OS) or Modern (light OS) via `prefers-color-scheme`; Editorial is an explicit operator pick (it's a third option, not an OS-level concept).

### Known limitations (carried into v0.3)

- **Pending-link approval is API-only.** Operator runs curl against `/v1/identity/links/pending/{id}/approve` until the UI panel ships.
- **Memory search returns 503.** Storage half is done; sentence-transformers embedding backend (and the GET path) is the deferred piece.
- **One conversation per Discord message.** Each inbound message starts a fresh conversation; threading lands in v0.3.
- **NT modulation parameters are empirical placeholders.** Defaults work but haven't been tuned against real operator observation data.
- **No streaming chat.** `/v1/chat/stream` returns 501.
- **One operator per install.** Multi-operator support is v0.3+.
- **Reflection is manual-trigger only.** NT-driven idle-state mind-wandering is v0.3.
- **No voice-driver awareness of NT state.** v0.2 picks the voice driver from operator config; v0.3 should make this NT-aware so anxious Eugene picks a terser model than calm Eugene.

### Migration from v0.1

v0.1 installs need to:
1. Pull the new v0.2 repos (`identity`, `connector`, `memory` with v0.2 backend, watchdog with auth, all components with v0.2.x voice-pass + agreement scorer).
2. Run the wizard from scratch — v0.1 didn't persist a passphrase. The wizard's first-run path will set one up.
3. v0.1 `defaultSystemPrompt` is replaced with the thicker v0.2.x default. Custom prompts are preserved if you've already edited yours.
4. Hemisphere-driver configs from v0.1 keep working — the `provider` / `modelId` shape is unchanged. `thinkingMode` defaults to `auto`.

### Component versions

| Repo | v0.2.0 HEAD |
|---|---|
| `specs` | `052fd19` |
| `orchestrator` | `9c26fe0` |
| `hemisphere-driver` | `254038e` |
| `ui` | `9196d5b` |
| `watchdog` | `f84ab84` |
| `memory` | `3fbf9b2` |
| `identity` | `ca19f0a` |
| `connector` | `3c8e1e1` |

---

## v0.1.0 — 2026-05-10

The initial release. A working bicameral loop across two hemisphere-driver instances, served through a Next.js UI.

- Five hemisphere-driver adapters: `anthropic_api`, `openai_api`, `claude_code_cli`, `codex_cli`, `openai_compat_http` (Ollama / vLLM / LM Studio).
- HTTP+JSON + OpenAPI 3.1 schemas for all cross-component contracts; `datamodel-code-generator` (Pydantic v2) + `openapi-typescript` codegen.
- Bicameral loop with Jaccard agreement scoring + multi-pass termination on consensus.
- Per-driver Test buttons, the remote-config protocol on every component, degraded-mode startup so bad config can't soft-brick the install.
- Watchdog process supervisor with orphan-kill protection (Job Object on Windows, prctl on Linux).
- First-run wizard (7 screens — pre-Security, pre-component-split).
- Six body components: orchestrator (8080), 2× hemisphere-driver (8081/8082), memory (8083), UI (3000), watchdog (8079).
