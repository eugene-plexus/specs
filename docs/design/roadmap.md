# Roadmap

**The one roadmap, from 2026-10-21.** It holds every unfinished slice found by
an audit of the six roadmaps, every design doc, the memory files, the handoffs
and the open GitHub issues (2026-10-21). It replaces six roadmaps, retired
the same day; their full text is in `docs/history/`:
[`audience-roadmap.md`](../history/audience-roadmap.md),
[`adoption-roadmap.md`](../history/adoption-roadmap.md),
[`release-roadmap.md`](../history/release-roadmap.md),
[`experimental-model-roadmap.md`](../history/experimental-model-roadmap.md),
[`workbench-rich-content-roadmap.md`](../history/workbench-rich-content-roadmap.md)
and the milestones of
[`local-inference-control-plane.md`](../history/local-inference-control-plane-milestones.md).
The order is a first draft for Troy; his setups review may move rows.

**What is on it.** Only work left to build. An item that owed nothing but a
person's test was cleared (Troy, 2026-10-21); see "Cleared". Bugs live in
GitHub issues, not here.

**The order (Troy, 2026-10-21).** What is more fundamental comes first: work
that costs more the later it is done, such as contracts other slices build
on, data formats and migrations, and security that must reach installs
before stable releases carry the feature it protects. After that, what helps
the most people comes first.

**Columns.**
- **From** names the source IDs. The design behind them keeps the calls and
  "what building found".
- **Size:** S is under a day, M is one slice, L is several.
- **Risk** follows the testing policy: high means auth, privileges,
  destructive file operations, migrations, installers or release gates.

## 1. Foundations: cheaper now than later

Rows 3-6 should reach installs before a stable release carries LT1 (TLS
between machines). The next release fits after row 6.

| # | Slice | From | Size | Risk | Who | Why here, and what it needs |
|---|---|---|---|---|---|---|
| 1 | **Contract cleanup in one regeneration.** Cover four things: the decision backend's model revision (the contract promises a field the gateway drops), the dead `uiTheme`/`uiFontSize` settings, client `cache_control` carried to hosted Claude, and a check that every consumer's codegen lists each `openapi/*.yaml` | B2-REV, SET-1, PC6, codegen audit | S | cross | everyone; PC6 cuts hosted-Claude cost | Every consumer regenerates once, not four times, before rows 10-11 change contracts again. Call B2-REV (add the field, or fix the sentence) |
| 2 | **The shared acceptance harness behaves like the real server.** It needs the console log copy, the machine port and the client doors | memory `project_acceptance_and_instrument_traps` | M | cross | developers | Every later acceptance run goes through it. Today a check through it tests the harness, which is the project's recurring failure |
| 3 | **Rotate a machine's TLS key.** Two pins across an overlap | LT-ROT (`tls-between-machines.md`, later) | M | high | multi-machine | Today a changed root key strands every node. It needs a short design |
| 4 | **Agents learn a promoted root's address.** The endpoint and epoch reach the agents, and a pre-LT1 standby gets its pins | WS-ADDR, LT-OLDSB (`warm-standby.md`, "Found, not fixed") | M | high | multi-machine | The "root moved" contract that automatic takeover and every later standby build on |
| 5 | **Rotate the sign-in key, and change Eugene's passphrase** (re-sealing, the standby's copy included) | SI-ROT, SI-PASS (`sign-in-with-eugene.md`) | S+M | high | everyone who signs in | Rotation is cheapest while few apps cache the key. A passphrase that can never change is a hole |
| 6 | **Cut a patch release from a release tag while `main` has moved** | REL-PATCH (`release-script.md`; memory `project_issue_intake`) | S-M | high | everyone on stable | `release.py` qualifies `main`. A fix for stable has no path today |
| 7 | **Remove a person's data when the person is removed.** This covers chats, notes, documents, the past-chat index, server banks and connections, plus the rule for a person re-created later | W4, MRC27 (`workbench-v1.md`, `workbench-memory-and-documents.md`) | M | high | multi-person installs | Each new store adds another place to purge. Call MRC27 |
| 8 | **Installer pass.** Run the Mac service as a system daemon, which makes the macOS autostart claim true, and let both installers take `--label` | R2.6-mac, PLAT-START, NL-INST | M | high | Mac, multi-machine | Moving from a LaunchAgent is a migration, cheapest while Mac installs are near zero. Accept on GitHub's macOS runners |
| 9 | **Engine cache settings on a profile, sized from the machine.** This means `--cache-ram`, `--cache-reuse` and `--ctx-checkpoints`, with a RAM cache computed from free RAM; vLLM's CPU KV offload; and admission counting both | PC7, LD2 | M | cross | everyone running local models | The home of CB4's setting, DI2 and LD2. Measure llama-server's cache-update pause first. Call LD-C5 |
| 10 | **Measure people served at a speed.** A 1..N stream sweep through the gateway, adding agent-shaped load: hour-long sessions, the published pauses, and sub-agent bursts of 7-51. Report the knee, kept per runtime with its provenance | DI3, LD5 (replaces the 1-256 load test and creators items 1 and 3) | M | low | businesses; feeds rows 11, 13, 14 | Its result record is read by LD1's acceptance, DI5/LD3, the speed nudge and the creators' cards. Handoff `docs/private/handoff-di3.md` |
| 11 | **One fair queue in the gateway.** Waiting for a starting runtime, waiting for room in a pool, and a key over its concurrency limit become one queue, ordered by band, then person, then arrival. Refusals name their cause, and queue time is recorded | LD1, with WAKE and CB-C | M-L | high | every shared machine and agent user | One waiting mechanism before a second one appears. LD-C2 taken 2026-10-21: queue, reversing A5's no-queue rule. Calls LD-C3, LD-C4, WAKE and CB-C. One adversarial review |
| 12 | **Metrics export with names that last.** Prometheus `/metrics` on the gateway's own port, an optional OTLP exporter set from the console, decisions written as request rows, and the stored rollups served | LD4, B2-MET, MET-RU, the setups pass's Prometheus item | M | cross | businesses | Metric names become a public contract. Settle them once, before alerts and dashboards (row 38) depend on them |
| 13 | **Checked engine updates, and the drain they need.** Check a new build against the old one, roll the replicas, keep the old build on failure, and stop a gateway restart cutting streams | DI1, rolling upgrades (release §8, adoption, open threads) | L | cross | every install | Every install updates engines. The drain is reused by rows 15 and 40. Call DI-C3 |

## 2. Speed for everyone running local models

| # | Slice | From | Size | Risk | Who | Why here, and what it needs |
|---|---|---|---|---|---|---|
| 14 | **Wait or move by predicted time to first token; place new conversations by the tokens a replica holds.** Calibrate peak prefill per runtime (retained metrics, or a prompt-processing run in the profile benchmark), and read vLLM's `/load` | DI5, LD3, M4-LOAD, MD `--n-prompt` sweep | M | low | multi-replica installs | Needs row 10. Adopt only what beats CB3's rule |
| 15 | **Keep the prompt cache on disk across restarts** | DI2 | L | high (chats at rest) | everyone running local models | Needs rows 9 and 13, and a privacy review. Measure a hybrid model too. Call DI-C4 |
| 16 | **Apple unified memory in fit.** Fit misjudges a Mac worker today | LIB-PLATFORM | S | low | Mac | A fit verdict that is wrong is a setting that lies |
| 17 | **DFlash and EAGLE3 draft sidecars.** ggml-org already ships the files, which Eugene hides | SD-x, DFLASH | S-M | low | speed seekers | Builds on SD1 |
| 18 | **DeepInfer's small checks.** A truncated GGUF found before launch, vLLM's compile cache surviving a restart, 400s naming the field, trust-remote-code off by default | DI checks | S | low | everyone | Cheap. Each check that finds something is fixed in the same slice |
| 19 | **Repetition stop on by default, with evidence** | REP (`repetition-protection.md`) | M | low | everyone | Labelled evaluation, then compare with vLLM's detector |
| 20 | **"Same answer every time" setting** | DI7 | S | low | businesses, evaluations | vLLM's batch-invariant mode; measured on llama.cpp |

## 3. Features for the most people

| # | Slice | From | Size | Risk | Who | Why here, and what it needs |
|---|---|---|---|---|---|---|
| 21 | **The model author's sampling as a profile's defaults** (shown today, not applied) | M2-SAMP | S | low | everyone | Small and touches every chat |
| 22 | **Re-point a Library entry whose file moved** | M2-RELOC | S | low | everyone | Must never apply a profile to the wrong file |
| 23 | **Folder access for Workbench without a terminal.** The agent sets and removes the folder permission from the UI | C6-ACL (`workbench-files.md`) | M | high (privileges) | every Workbench folder user | Today an administrator runs `icacls`, which breaks the no-terminal rule. One review |
| 24 | **Client keys: rotate, and record last use** (`lastUsedAt` is never written) | CLIENT-KEYS (memory `project_agent_findings`) | M | cross | every app and tool user | Key hygiene for every connected client |
| 25 | **Connect an app on this machine.** The person's Job Site writes Claude Code's and Codex's setup, and Open WebUI gets a ready setup | CONNECT (audience roadmap), MR9b Open WebUI | M | high (auth, home-folder writes) | agent-client users | Needs a design. One review and a real-machine run |
| 26 | **Long chats that outgrow the context.** Workbench compacts or summarises a chat that grows past its model's context | rich-content roadmap, out-of-scope list | L | cross | every Workbench user | Design first |
| 27 | **Memory extras.** Send my past chats to a memory server; model-proposed merges; provenance from web and tool results; more servers and install-wide servers; projects with their own folder, model and owner view | MV5-backfill, MV6-later, MV5a-later, MV7-later (not sharing) | S-M each | low-cross | every Workbench user | Call MV5-C4 for the backfill |
| 28 | **Answer branches: delete, name, compare** | AV-later | S-M | delete is destructive | every Workbench user | |
| 29 | **Pictures in tool results.** One shared contract for images sent to the model, with the Job Site and MCP caps | RC3-caps | M | cross | every Workbench user | The contract lands in specs before any consumer uses it |
| 30 | **Documents and folders extras.** Map-reduce over whole documents, opt-in OCR, PDF click-through, collections, Job Site folders, a file watcher, per-folder intervals | MR-later, MR7-later, MRC26 | M each | cross | every Workbench user | |
| 31 | **Reading and rich-content extras.** Display settings, speaker labels, CJK, a heading outline, artifacts from tool results, revision diffs, more chart types, a per-chat run switch, Firefox and Safari | RD-later, RC-later | S-M each | low | every Workbench user | Do them in batches |
| 32 | **Skills** (Anthropic-style) | memory research | M | cross | every Workbench user | Design first |
| 33 | **Console: keyboard navigation in the resource tree, and settings search in the header** | UI-TREE-A11Y, SET-x | M | low | console users, accessibility | |
| 34 | **Open WebUI: hub search, images, updates** | C4-NEXT | M | cross | Open WebUI users | Includes deciding on `ENABLE_PLUGINS` |
| 35 | **Tray: unload models and keep serving** | R2.6-TRAY | M | high (a new credential) | Windows | Needs a narrow credential the tray can hold |

## 4. Several machines, businesses and vLLM

| # | Slice | From | Size | Risk | Who | Why here, and what it needs |
|---|---|---|---|---|---|---|
| 36 | **Machines says why a machine's announcement was refused** | R2.4-a | M | cross | multi-machine | Today it shows a probe error. A contract field plus an issue kind |
| 37 | **Routing profiles per person or group** (shared accounts, part two) | SSO-ROLES (`shared-accounts-and-sso.md`) | L | high | businesses | Designed 2026-10-16. Fix its data format before more per-person settings arrive |
| 38 | **Dashboards for administrators: alerts, SLOs, longer retention, fleet views, wake cost** | ADM, HH-NEXT, MD-x | L | low | businesses | Needs row 12 |
| 39 | **Operations rights for people who are not the owner** | CX-OPS | M | high | businesses | |
| 40 | **Usage and money limits per person and key** | KEY$, Shop, AD-BILL | L | high | businesses | Builds on A5's attribution |
| 41 | **Speculative decoding on vLLM**, including the overdue live vLLM run on current Edge | SD2 | M | low | vLLM | |
| 42 | **vLLM from its official container image** | VDK (business candidate) | M-L | cross | vLLM, businesses | |
| 43 | **Hardware health readout, and restarting on the cards that are left** | HWR, DI6 | M | low | multi-GPU | Host history already has temperatures |
| 44 | **Move a conversation's cache before planned maintenance** | DI2b | L | high | multi-machine | Needs rows 13 and 15 |
| 45 | **TLS for clients, next: DNS-01 ACME and tailnet certificates; narrow or rotate the CA; a header deadline on 8079** | LT2-ACME, LT2-CA | M | high | businesses | |
| 46 | **Node keys that cannot be exported, and freeze enforcement** | TOK-RES | M | high | multi-machine | |
| 47 | **Shared team knowledge, and sharing a project** | MRC25, MV7 sharing | L | high | businesses, MSPs | Call MRC25 |
| 48 | **The Library at scale.** Paginate `/v1/models`, then design an answer to "the Library is down" | M2-PAGE, LIB-RED | S, then L | cross | businesses | Redundancy is design first |
| 49 | **Which machine hosts a model** | M6-PLACE | L | cross | multi-machine | Design first, after row 14 |
| 50 | **One model across machines with llama.cpp's `rpc-server`** | RPC (setups pass) | L | cross | multi-machine | Design first |
| 51 | **Job Sites, banked items.** QR pairing, a re-pair warning, an auditor role, the worker checking signatures, Windows confinement, a tailnet origin | J-BANKED | S-M each | some high | multi-machine | |
| 52 | **Per-person isolation for local MCP programs** | C5b-iso | L | high | multi-person installs | |

## 5. Doors, developers and the platform half

| # | Slice | From | Size | Risk | Who | Why here, and what it needs |
|---|---|---|---|---|---|---|
| 53 | **One store for the platform half.** Design how files, batches, vector stores and stored responses are kept, owned and expired | PLAT (memory `project_platform_half_on_roadmap`) | M | high (store, migrations) | developers | Rows 54-56 share it, so design it once |
| 54 | **Stored responses, with the chain as the conversation key** | LD6 | M | high (chats at rest) | agent clients | Today `previous_response_id` gets a 400 |
| 55 | **Batch jobs in idle time**, run as background-band traffic | LD7 | M | cross | developers, home batch jobs | Needs rows 11 and 53 |
| 56 | **Files, vector stores and `file_search`** | MRC24 | L | cross | developers | Call MRC24 |
| 57 | **Responses: non-function tools and `compact`** | RSP-T | M | low | developers | |
| 58 | **A Gemini API door**, and the small Gemini items (mp3/opus speech, countTokens, dimensions) | GEM-D (gateway#5), GEM-x (inference-driver#7) | L, S each | low | Gemini SDK users | |
| 59 | **More server-run tools.** Tavily, and remote MCP on Responses | P8-later | M | cross | developers | |
| 60 | **Full interop conformance.** A separate-origin MCP proxy, network and device grants, sampling and elicitation, A2UI beyond forms | G-later | L | high (sandbox) | developers | |
| 61 | **LoRA adapters as Library items**, routed to replicas holding them | M2-LORA | M | cross | developers | |
| 62 | **A `runtime_name` dropdown** in place of free text | M4-DROP | S | low | developers | |

## 6. Engines and the Library's reach

| # | Slice | From | Size | Risk | Who | Why here, and what it needs |
|---|---|---|---|---|---|---|
| 63 | **Strata: the speed projection, and several GPUs** | STR-14 (agent#14) | M | low | multi-GPU | |
| 64 | **Starter set: proof of CPU speed** | LIB-STARTER | M | low | CPU-only users | |
| 65 | **Ollama: keep a model in the Library, and read a worker's own Ollama store** | CX9-KEEP | S-M | cross | Ollama users | |
| 66 | **Experimental engines: TensorSharp, NInfer, imp** | ENG-X, A8-NEXT | M each | low | tinkerers | |
| 67 | **Local image models and local media**, with their own admission design and more catalogue sources | IMG, MEDIA-LOCAL, MED-later, SRC | L | cross | image users | The audience research found no demand yet. Troy banked it for after v0.2 |
| 68 | **DeepSeek V4.x Flash through Eugene** | DI8 | M | low | Mac, businesses | Needs borrowed hardware |
| 69 | **Creators items 2, 4, 5 and 6.** A benchmark matrix, a shareable card, a presentation view, a public dataset (which needs a privacy design) | CR2, CR4-CR6 | M-L | low; dataset high | creators | Troy put these at the back (2026-10-18). Needs row 10 |

## Waiting on a call from Troy

These are blocked until the call is taken:
- **MV5b, Hindsight installed from the catalogue** (`workbench-memory-v2.md`): call MV5b-C1, where pg0 keeps its data on Windows. Its store migration must become 27 → 28.
- **Installing vLLM for the person**: the recommendation is to use their own install and defer.
- **The installer's `--channel` flag** (`settings-accuracy.md`).
- **Dependabot grouping in every repo.**

## Not scheduled without Troy

- **The standby takes over by itself** (WS-AUTO). It goes after row 4.
- **Job Sites:**
  - cross-site copy, with calls J92-J99, and the root MCP endpoint that comes after it;
  - an owner setting people's passwords (J12);
  - a standalone site install (J21);
  - managed-fleet enrollment (J16).
- **Mutual TLS and connection-bound tokens** (LT-C3).
- **The check pipeline and the secret filter.** If scheduled, it goes before row 58, so each new door is wired into the checks once.
- **Realtime** (P7).
- **Blueprints.**
- **Gemini code execution** (inference-driver#8).
- **A separate draft model** (SD3).
- **PB2's remainder:** the model's row saying when fit placed a profile differently, and "make it faster" on Home.
- **The Library deposit endpoint** (AS-8).
- **Retiring the three-port Compose file.**

## Banked: built only when a trigger arrives

- Type coercion of tool arguments (A5-5), if a current model needs it.
- A runtime venv per component, when component dependencies conflict.
- Merging two gateways' metrics, if a second gateway is ever built.
- vLLM-Metal and multi-node vLLM.
- A per-format default engine (L10), and measured speeds for the nudge (LS9m, after row 10).
- The TypeSafe SDK example, when TypeSafe ships its SDK.
- Vercel's `/v1/evaluate`, once a real client exists to test it.
- Retiring DI4's escape per engine build, once llama.cpp #28249 lands.
- A reservation over-counted while loading (R3.2-b), when an engine reports load progress.
- Research orchestration, a code-execution service, an Office editor.
- SAML, tenant hierarchies, multi-region HA, compliance; automatic rollback, offline install, reproducible builds.

## Calls waiting for Troy

- **Blocking a row:**
  - B2-REV (row 1)
  - MRC27 (row 7)
  - LD-C5 (row 9)
  - LD-C3, LD-C4, WAKE and CB-C (row 11)
  - DI-C3 (row 13)
  - DI-C4 (row 15)
  - MV5-C4 (row 27)
  - MRC25 (row 47)
  - MRC24 (row 56)
  - MV5b-C1 (see "Waiting on a call from Troy")
- **Defaults already built, to confirm:**
  - MV2-C1, MV3-C1, MV4-C1 to C3, MV6-C1 to C5, MV7-C1 to C5
  - DI-C2
  - LT2-C6 (a 90-day leaf; decide it before stable installs hand leaves out)
  - CX4-C1
- **Settled by this roadmap unless Troy changes it:** DI-C1 (all of DI1-DI8 are placed above) and LD-C1.
- **Other:**
  - DI-C5 (recommended: do not wrap DeepInfer)
  - LD-C6 (how Eugene describes itself)
  - MRC26 and MRC28
  - MD-24 (reasoning rendered as Markdown)
  - more than one standby
  - the console logo's outline
  - config shown four times in the map panel
  - keeping the ~48 GB of measurement models in `C:\mr8-models`
  - when to deploy the website batch
  - keeping the `lt1` and `lt1-image` branches

## Cleared: only a person's test was owed

Troy, 2026-10-21. These are built. What they still owed was a run by a
person, on hardware or accounts the project does not have, so they are not
carried forward:
- **Sessions and live checks:** moderated friend sessions (S10); the first
  real `release.py` run, which happens at the next release; the CI-flake
  watch; the TLS cost on a real engine.
- **Windows service and installer:** reboot-before-sign-in, tray and
  service-stop checks (R2.6, agent#20); installer `--join` end to end;
  Compose check 18.
- **Hardware we don't have:** a physical Mac and Mac/Linux path mappings
  (A4, R3.7, M11); native Linux boot; SYCL, OpenVINO and Arc; an 8 GB GPU
  baseline; two real GPUs; Kev on CUDA, ROCm and Metal.
- **Live or credentialed runs:** live vLLM runs (M4); hosted Jev through
  TypeSafe; Brave, image tools and Anthropic block captures (P8); the
  Anthropic `refusal` capture (R3.4); agent and gateway paths never run live.
- **Trust failure modes:** offline-node rotation, clock skew, a partitioned
  root, the sealed key across a container restart (M5); a promoted root
  under the keyring or passphrase file; the trust-design review.
- **Multi-machine:** the re-enrollment walk (R2.4-b); clearing `controlUrl`
  on the live install (M9); Job Sites physical checks.
- **Workbench:** MCP against real clients; MR6b on real questions; RC6 on
  Troy's install; accessibility and phone checks.

Build work a test once found stays above. The bugs go to GitHub, below.

## Defects found by the audit, filed as GitHub issues

These are not rows. Each was filed on 2026-10-21 on the repo that owns the fix:
- [ui#21](https://github.com/eugene-plexus/ui/issues/21): a 401 from any one
  component signs the person out of the whole console.
- [control#10](https://github.com/eugene-plexus/control/issues/10): PATCH
  accepts `securityMode: os_keyring` without checking the keyring works.
- [agent#23](https://github.com/eugene-plexus/agent/issues/23): runtimes
  started at boot skip memory admission (was R3.2-a).
- [workbench#17](https://github.com/eugene-plexus/workbench/issues/17): four
  small memory defects left from MV3 and MV6.
- [library#16](https://github.com/eugene-plexus/library/issues/16): an Ollama
  model's served name follows tag sort order, and symlinked folders are
  protected only in text.
- workbench#16, a flaky test, was already filed.

Not filed: a restart re-arms the NAS's 15-minute entry-point revert clock.
`entrypoint_setup.py` says the window runs from each start, so the code does
what its design says. File it only if Troy wants the deadline kept across a
restart.

## Housekeeping, not slices

- `support-matrix.md` still describes v0.2.0. Refresh it at the next release.
- Leftovers on this machine: the `hs` venvs, the `mv5b-*` pg0 instances
  (Windows and WSL), the gemini-cli scratch copy.
- Local venvs on Python 3.12, so `test_job_sites` stops failing only here.
- The memory note about the cross-component test repo not being in CI:
  confirm specs CI's pinned integration covers it, then retire the note.

## How the old roadmaps were retired (2026-10-21)

1. Each old roadmap keeps its file in `docs/design/` as a two-line stub, so
   links from other docs still resolve.
2. Its full text moved to `docs/history/`, with its links rewritten to
   resolve from there.
3. `CLAUDE.md`'s "What to work on" and the README point here.
4. The stale status lines the audit found were fixed in the same change.
