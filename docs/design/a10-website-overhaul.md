# A10: eugeneplexus.com for v0.2.0 (plan)

**Status: built 2026-10-13 (website `f428560`); the Pages deploy waits for Troy's OK.** Roadmap row A10 in
[audience-roadmap.md](audience-roadmap.md). Sources of truth:
[v0.2.0 release notes](../releases/v0.2.0.md), the
[release run](../acceptance/v0.2.0-release-run.md), the dated records in
`docs/acceptance/`, and [support-matrix.md](../support-matrix.md) once it is
brought up to v0.2.0 (step 1 below).

## 1. Inventory

| Page | Stale for v0.2.0 | Missing |
|---|---|---|
| `/` (index) | Uses: coding tools name Claude Code, Continue, Cline only. Workflow: Discover reads as "versions that fit", no per-engine "Works here now"; Route has no providers or tools. Platform card: llama.cpp + vLLM only. FAQ is a changelog ("Since alpha.5… Since alpha.6… Since v0.1.0"); chat-app answer is alpha.6 Workbench; engines answer has no Strata; privacy answer predates hub sources and Gemini; machines answer has no warm standby or Job Sites. Roadmap link goes to the superseded `adoption-roadmap.md` (asserted in website.spec.ts:27). Screenshots predate both copy passes | Workbench memory and documents, Job Sites, providers, search models, as uses. Links to the new pages |
| `/install` | Help says `systemctl --user status`, but the default Linux install is a system service. Docker section starts "Since alpha.3"; its Compose is the legacy direct-port setup, while container.md now recommends one HTTPS port for new setups. Windows "older per-user installation" migration paragraph is alpha-era (check install.ps1 at the tag). Offline-removal copy omits Linux per-user installs. Dead `!offlineRemoval` branch. Recipes link says "Open WebUI and Claude Code" only | The seven "Moving to v0.2.0" steps (source order, Strata reinstall, hub token, Open WebUI reset, app-key limits, `/runtimes`, theme). A pointer to Install Workbench |
| `/architecture` | Hero "v0.1.0 snapshot, October 2". `#status` is a v0.1.0/alpha history (five e2e assertions). Components: no tool-driver, no apps (Workbench, Open WebUI), no site-host; agent, library, gateway and control cards lack their v0.2 jobs. Engine chips lack MLX, Strata, Kev; tool chips lack Codex, Workbench, Open WebUI. Two roadmap links to `adoption-roadmap.md` | Search models and `/v1/rerank`, the ignored-settings header, tools assumed, the loading-replica skip, Library sources and per-engine eligibility, Job Sites, warm standby, HTTPS. Glossary: Job Site, search model |
| `/recovery` | Version notice still carries the closed specs#11 claim, which contradicts the guide's own table. Footer "reviewed September 29, for alpha.5". Meta description lists only alphas. Four alpha paragraphs at full length | v0.2.0's converted files and their `.v0.1.bak` copies, in one line. The snapshot `src/content/recovery.md` already matches docs/recovery.md at the tag; the README still says `ee3acf1` |
| `/cache-aware-balancing` | Nothing false. A dead pre-release branch (`shipped` false) | — |
| `/first-search` | Nothing false (a dated story) | — |
| `/principles` | No version-bound claims | — |
| `/llms.txt` | "Development roadmap" → `adoption-roadmap.md`. Support matrix and application workflows link the tag, where both are stale | The new pages (through `public-pages.json`) |
| `/404` | — | — |
| SiteLayout | Default description "First release available." (website.spec.ts:11) | New pages in the footer; header nav (below) |
| `sitemap.xml`, `public-pages.json` | — | The new pages |
| README | Status "v0.1.0-alpha.6… No stable release yet"; "only Eugene source revisions are fixed" (the manifest now hashes Python dependencies); recovery snapshot "ee3acf1 (alpha.6)"; "Keep the pre-release notice"; roadmap link `release-roadmap.md` | A v0.2.0 block in Copy Evidence |

## 2. New content

### Pages

- **`/features`, "What Eugene does"** (new). One section per v0.2.0 area that
  is not its own page: the Library built around engines; search models; tools
  on every model; providers; Strata (experimental); machines and install. Each
  section has one lead line (what it does for the reader), a screenshot where
  there is one, a **Details** disclosure, links to its guides, and its known
  issue in plain view. Workbench and Job Sites appear
  as cards linking to their pages.
- **`/workbench`** (new). Chat with memory, documents in a chat, saved
  documents and granted folders searched by words and meaning with cited
  passages, the toolbox with per-call approval, answer versions, and the media
  screens. Links to its guides. Known issue: the sorter's default time suits a
  GPU, not a typical CPU.
- **`/job-sites`** (new). Workbench on your own machines, wherever they are:
  one command to join, no incoming connections, no VPN or cloud; each person's
  tools as their own account with their own keys; risky calls held; access
  windows close. Links to its guide. Known issue: no copying between machines
  yet.
- **Home** keeps its shape. Uses grow from four to six. Workflow and FAQ
  state what v0.2.0 does, not when each piece arrived. New screenshots.
- **Header nav** stays at six links: What it does → `/features`, Workbench,
  Install, Questions, Architecture, Our principles. "See it" leaves the header
  (its anchor stays). Job Sites is linked from `/features`, Workbench and the
  footer.

### Guides (Troy: `/guides`, one page per guide, for search; more will come)

`/guides` lists them; each is `/guides/<slug>`, written as Markdown in
`src/content/guides/` so a new guide is one file. Each has at most six steps
in the console's and Workbench's labels at the pinned commits (ui `a483c9e`,
Workbench `d5aad5f`), and is linked from its feature's section.

| Guide | Slug |
|---|---|
| Update from v0.1.0 (root first; the seven Moving steps) | `update-from-v0-1-0` |
| Add a cloud provider or subscription (Gemini, OpenAI, OpenRouter, ElevenLabs, Claude Code, Codex) | `add-a-provider` |
| Add a web search account and set its order | `add-web-search` |
| Run a search model and a result sorter; Open WebUI's document search | `run-search-models` |
| Connect Codex or Claude Code | `connect-codex-and-claude-code` |
| Find, check and delete a model; add a hub source | `manage-models` |
| Install Workbench | `install-workbench` |
| Give Workbench documents, folders and tools | `workbench-documents-and-tools` |
| Set up a Job Site | `set-up-a-job-site` |
| Add a warm standby | `add-a-warm-standby` |
| One HTTPS port for the container (optional) | `container-https` |

`/install` keeps install, first reply, update and removal; its update section
links the update guide.

## 3. Screenshots

| # | Screen | Page |
|---|---|---|
| 1 | Home, a first reply (replaces `first-reply.webp`) | `/` |
| 2 | Home at phone width (replaces `phone-first-reply.webp`) | `/` |
| 3 | Use it from your apps, with the Codex recipe (replaces `connect-your-apps.webp`) | `/`, `/features#tools` |
| 4 | Discover, "Works here now", a detail with each engine's reason and fit | `/features#library` |
| 5 | A model page: "Runs as", and the Delete confirmation listing files | `/features#library` |
| 6 | Settings → Where to find models | `/features#library` |
| 7 | Backends, adding a Gemini account (form empty, no key typed) | `/features#providers` |
| 8 | Routing → Web search order | `/features#providers` |
| 9 | Machines with update status, two demo machines | `/features#machines` |
| 10 | Metrics, Request outcomes | `/features#machines` |
| 11 | Workbench answering from an attached document, naming the file | `/workbench` |
| 12 | Workbench's Memory page | `/workbench` |
| 13 | Workbench citing a saved document's passage by file and page | `/workbench` |
| 14 | Workbench holding a tool call for approval | `/workbench` |
| 15 | Workbench at phone width | `/workbench` |
| 16 | Workbench's Job Sites page, from Amish_Station's real Job Site (Troy's call), names altered | `/job-sites` |

No Strata screenshot: it needs a GPU, and this run is CPU only.

**How they are made.** Extend `scripts/website-screenshots.{py,mjs}` (S9's
isolated install: real packaged UI and components, random free ports, every
ambient `EUGENE_PLEXUS_*` cleared, nothing intercepted).
- Never the live install: no default port, no service, the prefix under a
  neutral path such as `D:\eugene-demo` so no shown path names an account.
- Engines on the CPU: llama.cpp's CPU build only. Qwen3-0.6B for the console
  shots, as today; Gemma 4 E4B Q4_K_M for Workbench answers; the small search
  and sorting models from the MR3 and MR6 records.
- Workbench from the agent's catalogue at the pinned dist (C3's path). A second
  isolated agent joins on the same host for Machines.
- Demo data written for the shots: machine names `desk-pc` and `garage-nas`;
  people `Sam` and `Riley`; a fictional community-garden handbook (PDF and CSV);
  three memory notes; a folder tool on the demo folder; a key named `laptop`.
  About twenty requests so Metrics has data.
- **A leak check that can fail:** before each capture, the script reads the
  page's text and stops if it holds the Windows account or host name, `Troy`,
  `troyc`, `Amish`, `192.168.`, `C:\Users`, or a key prefix (`sk-`, `AIza`).
  Sabotaged once with the real host name.
- Troy's call: processor and graphics card names may show; machine and user
  names are altered in the page before capture, and the leak check proves it.
- Shot 16 alone uses the live install, read-only: Troy signs in to a headed
  browser, the script opens Job Sites, replaces the names and captures.
- Desktop at 1440 wide and phone at 390, at 2× scale, in the same console
  theme as today's shots; converted to WebP. The `runner` runs it; I review
  every image before it enters the website repo.

## 4. What the site will not claim

- Every claim traces to the release notes or a dated record, listed in the
  README's Copy Evidence. Numbers appear only with their conditions (the
  sorter's 0.6 s on a GPU and 7 s on a CPU; Open WebUI keys' 8 at once and 600
  a minute).
- All six known issues stay visible: on their feature's section and together
  on `/architecture#status`.
- Labels stay: Strata **experimental** (text only, one GPU, one request at a
  time, unknown memory fit); Kev decision models experimental; Mac checked on
  GitHub's runners, not a physical Mac; the container's GPU path and a Windows
  reboot before sign-in are pending; "early software, with known limits".
- Not mentioned as available: copying between Job Site machines; memory
  suggestions and the MCP door (MR8, MR9); image models in the Library;
  Anthropic document blocks; full vendor API parity; capacity or speed beyond
  the records; any comparison beyond the dated cache-aware page.
- Mechanisms, not adjectives: "no incoming connections", "as their own
  account", "signed with keys only that person holds", never "secure".

## 5. Linked specs docs, fixed on main, then repointed

The site links these at the tag; each is stale there.
- `docs/support-matrix.md`: "as of 2026-10-08, after v0.1.0" and the *since
  v0.1.0* markers. It has no rows for memory and documents (MR1-MR7), search
  models and rerank, Gemini and Google Search, tools on every model, or the
  Library's sources, eligibility and delete. The Strata row may predate the
  real run; reconcile it with the records.
- `docs/deployment/uninstall.md`: "development installers after v0.1.0".
- `docs/application-workflows.md`: "These recipes target the A4 development
  build, not the frozen alpha"; Claude Code 2.1.207; no Codex recipe.
- `docs/deployment/container.md`: uses Troy's NAS address (`192.168.16.252`)
  as its example; swap in a placeholder.

The website gets a `docsCommit` (a new `src/data/docs-revision.json`), used
for these links, `/llms.txt`'s documentation links, and the README.
`alpha-release.json` stays a copy of the published release; installers stay
on `specsCommit`.

## 6. Order of work

1. Specs main: the four docs above; push.
2. The screenshot harness and its run (the `runner`); I review the images.
3. Website: install and recovery, architecture, home, the three new pages,
   then layout, nav, sitemap, `llms.txt`, `public-pages.json` and README. Each
   page change updates its e2e assertions; new specs for the three pages;
   `plain-words` and `machine-readable` cover them.
4. The `runner` runs `npm run check` and `npm test` (320 to 1920 wide) before
   each push.
5. One adversarial review: claims against evidence, accessibility, phone
   widths. Fix; review again only for a blocker.
6. Push the website; Troy dispatches the Pages deploy.

## Troy's calls (2026-10-13)

1. How-tos go in `/guides`, one page each, for search.
2. Processor and graphics card names may show; machine and user names are
   altered or blurred.
3. The Job Sites shot uses Amish_Station's real Job Site.
4. Docker keeps the three-port Compose as the standard install for now; one
   HTTPS port is an optional guide. (He expects to deprecate three ports
   later; the site does not say so.)

## 7. Eugene, animated (Troy, 2026-10-13)

The site's four poses (welcome, guide, working, curious) are built from the
face SVG by `scripts/build-mascots.mjs`, as Workbench's seven scenes are.
Give them small loops the same way (CSS inside each SVG, pivots from
`getBBox`, still under `prefers-reduced-motion`), and show Workbench's own
working scenes on `/workbench`. One pose first for Troy's approval of the
style, then the rest. A browser check proves each moves, and holds still
under reduced motion.

## 8. What building found (2026-10-13)

- **The site said Anthropic documents were refused; they have been carried
  since 2026-09-28** (the P2a media-inputs record). `api-compatibility.md`
  also still refused structured output and unknown settings; corrected on main
  (specs `6b6892b`) from gateway `7b9a4c4`.
- **`application-workflows.md` still targeted "the A4 development build"**, and
  the support matrix had no rows for memory and documents, search models, the
  Library's engines, Gemini or tools on every model. Both fixed at `08899f2`,
  which the site now reads its linked docs at (`docs-revision.json`).
- **The sitemap had lost `/cache-aware-balancing`.** It is generated from
  `public-pages.json` now, as `/llms.txt` and the Markdown export are.
- **Labels:** about 70 console and Workbench labels in the guides were checked
  at ui `a483c9e` and Workbench `d5aad5f`. Workbench hides Job sites from the
  owner; ElevenLabs has no add path under Backends' "Which app?"; switching to a
  warm standby is not in the console. The site says each as it is.
- **Product bugs filed:** ui#18 ("See it on Inference"; Strata "no tools"),
  workbench#9 (a folder hint names a People section that is gone),
  workbench#10 (a Strata model is treated as an outside model, so memory is
  held back). Not filed, told to Troy: the "Where to find models" default shows
  as raw JSON; the Gemini key placeholder is "sk-…".
- **Screenshots:** the harness builds the v0.2.0 install as `install.sh` does,
  because a dev checkout says "Development build" on Machines. Its leak check
  matches names as words: the demo name `desk-pc` contains `sk-`. Two pictures
  came from Troy's live install (Job Sites, a web search chat); the first take
  missed his username, and a name swap would have rewritten a real GitHub issue
  title among the sources, so that take was dropped.
- **The review** (one round, Sonnet) found claims stronger than their records
  (folder sync, Let's Encrypt and Traefik, the Mac remover, fit for every
  engine, Strata's conditions, media screens) and unreadable desktop pictures
  at phone width; all fixed, and each desktop picture links its full size.
- **Eugene, animated:** Troy approved the wave after two fixes (the hand on
  the cuff, in front of the face). The check that each pose holds still for
  reduced motion was sabotaged once and failed as it should.
