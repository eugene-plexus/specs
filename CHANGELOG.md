# Eugene Plexus changelog

Cross-component release notes. Each repo has its own commit history; this file consolidates what shipped together.

---

## v0.2.0 — 2026-05-24

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
| `specs` | `764d4a1` |
| `orchestrator` | `650cc9b` |
| `hemisphere-driver` | `9f2cedc` |
| `ui` | `1efa1a6` |
| `watchdog` | `bb4de0e` |
| `memory` | `8ca8624` |
| `identity` | `3d60e1c` |
| `connector` | `a8ba3df` |

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
