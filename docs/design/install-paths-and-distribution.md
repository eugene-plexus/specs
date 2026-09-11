# Install paths and distribution

**Status: §9 steps 1 and 2 are BUILT AND LIVE-VERIFIED (2026-09-11);
steps 3-9 are still design.** Written before any implementation so a later session
could pick it up cold. Every claim marked *verified* was checked against
a repo, a registry or upstream on the day of writing; everything else is
reasoning and is marked as such. **§12 is the implementation record and
is the pickup point; step 3 (`install.sh` / `install.ps1`) is next, and
one decision inside it is open — see §12's step 2 entry.**

Precedes a release, deliberately. Publishing an installable thing whose
only install is a Windows developer script would bake the gap in.

## Decisions needed before building

Each has a recommendation in the section named, with the
counter-argument that would overturn it. **This block is the decision
log** — answers are recorded here as they are made.

| #      | The call                                                                              | §    | Decision                                    | Status                     |
| ------ | ------------------------------------------------------------------------------------- | ---- | ------------------------------------------- | -------------------------- |
| **1a** | Move the UI proxy into the agent?                                                       | §3   | **Yes — moved; the agent serves the UI too** | **DONE 2026-09-11, §12** |
| **1b** | Ship the UI as a static export, or as a Next server?                                    | §3.1 | **Export** — decided at the end of 1a, on evidence | **DONE 2026-09-11, §12** |
| **2**  | Linux + NVIDIA: ship Vulkan with a permanent visible degradation, or keep the refusal?  | §7   | **Ship Vulkan, badge it permanently**       | **DECIDED 2026-09-11**     |
| **3**  | macOS: first-class now, or wait for MLX?                                                | §8   | **First-class now, decoupled from MLX**     | **DECIDED 2026-09-11**     |
| **4**  | Windows: a supported end-user target, or a dev surface only?                            | §11.1 | **Fully first-class** — parity, not a middle tier | **DECIDED 2026-09-11** |
| **5**  | Where `install.sh` is hosted: `eugeneplexus.com`, or a raw GitHub URL first?             | §4   | *(recommended: GitHub URL now)*             | **OPEN**                   |
| **6**  | What does `install.sh` install FROM, given nothing is published and the release is last?  | §6.1 | *(recommended: GitHub archives at a tag)*   | **OPEN — blocks step 3**   |
| **7**  | Windows service: `pywin32` or NSSM?                                                      | §11.1 | *(recommended: pywin32)*                    | **OPEN — inside step 3**   |

**#1 was one call and is now two**, which is the substantive change
from the first draft. Troy's question — *"I intend for the UI to get
much more complicated and feature rich; do static pages still make
sense?"* — is answered in §3.1, and the answer is that **the two halves
are separable and only 1a is a commitment.** After 1a the UI is a pure
client application either way, so 1b collapses to one line in
`next.config.ts`: a build target, reversible after release. Do 1a; pick
1b late.

#2-#4 are independent of #1 and of each other. #5 is near-automatic and
is listed only so it is not forgotten at the last moment.

Deliberately **not** decided here: version policy, release workflows and
who tags what (§6). Those belong to the release, which follows this
work.

## 0. The reframe — two audiences, not two install systems

The project has two audiences and they look like they need different
installers:

1. **Home enthusiast.** One machine, wants to play with dozens of models.
2. **SMB.** Serving inference to dozens or hundreds of employees.

They do not need different installers. They need **the same two pieces,
co-located or not** — and the seam between those pieces already exists,
because M5 and M7 built it and proved it on two real hosts.

|                   | Home                        | SMB                                          |
| ----------------- | --------------------------- | -------------------------------------------- |
| **Control plane** | on the host, same install   | a container on an ordinary VM                |
| **Agent(s)**      | the same box                | host install per GPU box, then `join`        |
| **Commands**      | one                         | two, each one line                           |

The SMB topology is `scripts/m7-acceptance.sh` in `EP_MODE=two-host` —
the run that passed 41 checks on its first attempt with NAT and a host
firewall in between. **Audience 2's architecture is built and
live-verified. Only its packaging is missing.**

## 1. The constraint that decides everything

**The agent must run on the host; the control plane need not.**

The agent supervises GPU processes, downloads engine binaries into its
own directory, reads the user's model directories from the user's own
disk, and — per M4 — drives a vLLM whose unit of operation is "a Python
environment plus a C toolchain plus the interpreter's dev headers."
Containerising that buys `nvidia-container-toolkit`, a bind mount for
every model directory the user owns, and a container that JIT-compiles
at first use.

Home Assistant met this exact wall. It is the entire reason the awkward
"HA Supervised" tier exists beside their container image. Don't repeat
it.

`control`, `gateway`, `library` have none of those properties. No GPU,
no host processes, no user filesystem. They are ordinary networked
software and they containerise without argument.

## 2. What is true today (verified 2026-09-11)

- **`scripts/bootstrap.ps1` is the only bootstrap in the org** — 116
  lines, Windows-only. No shell equivalent, so Linux and macOS have no
  automated path at all.
- It is **a developer script**, not an installer: it clones seven repos
  with `gh repo clone` (so it needs an authenticated GitHub CLI, which
  no end user has), builds a venv per repo, editable-installs each with
  `[dev]`, installs pre-commit hooks, runs `npm install` + codegen for
  `ui`, then installs all four components into the agent's venv and
  asserts they import.
- **There is no end-user install path in any form.** Nothing on PyPI or
  npm; zero GitHub releases; **no repo has a release or publish
  workflow — every one has only `ci.yml`**. `control` and `library` have
  never been tagged at all; the newest tags elsewhere are
  consciousness-era `v0.2.0`.
- **Packaging itself is fine.** Five well-formed `0.1.0` packages,
  `requires-python = ">=3.12"`, one console script each
  (`eugene-plexus-<component>`).
- **The one-venv thesis holds.** `supervisor.py:418` spawns
  `[sys.executable, "-m", spec.module]`, and
  `default_topology.py:78-82` declares exactly `control` (8083),
  `gateway` (8080) and `library` (8082), each only if
  `importlib.util.find_spec` finds it **in the agent's own
  interpreter**. So one venv holding five packages, plus
  `eugene-plexus-agent`, *is* the whole Python install.

### 2.1 The gap nobody had written down: no install produces a UI

**CLOSED 2026-09-11 by §9 step 1 — see §12.** Everything below
describes what was true before that and is kept because the reasoning
is what chose the fix. The agent now serves the UI at root from the
`eugene-plexus-ui` wheel.

**The agent serves no UI.** The agent repo has no `ui/`, no static or
assets directory, and `app.py` includes six routers and mounts nothing
at root. CLAUDE.md's repo table has carried *"`ui` — 3000 dev, served at
8079 root"*; **the second half is false** and appears to be inherited
from the v0.2 watchdog, which did serve UI assets.

The UI is a standalone Next.js 16 server needing Node ≥20. Nothing
supervises it, nothing installs it, there is no Dockerfile for it, and
`docs/deployment/tailnet.md` says *"On A, open the UI"* without
anywhere saying how it got there.

So the one-venv install described above delivers an OpenAI-compatible
endpoint and **no browser at all** — which removes differentiator #5,
the thing that makes this a product rather than a shell script.

One correction to the same family of assumption, since it was nearly
asserted the other way: **the UI has been run in production mode.**
`m3-acceptance.sh:185` runs `npm run start` and line 89 asserts `.next`
exists. It is only the later multi-host scripts that use `next dev`, and
`npm run build` runs in the `ui` repo's CI, so the production build
works. The gap is distribution, not buildability.

## 3. The UI can stop needing Node, and should

Checked before recommending, because the answer changes the shape of
every install below:

- **The entire proxy is one file, 147 lines** —
  `ui/src/app/api/proxy/[target]/[...path]/route.ts`. It is not an
  architecture.
- **It is the only dynamic route in the whole application.**
- Every page is already `"use client"`. Only `layout.tsx` is a server
  component, which static-exports fine.
- No middleware, no server actions, no `cookies()`, no `next/headers`.
  One `next/image` call in `page.tsx`, needing `images: { unoptimized:
  true }`.

So `output: "export"` is reachable by deleting one route handler and
changing two config lines.

Move that proxy into the agent and it gets **simpler, not harder**: its
hardest job is asking the agent's bearer-protected `/v1/components`
where a target lives, which becomes an in-process function call instead
of an authenticated HTTP round-trip. The `x-eugene-plexus-upstream-authorization`
two-credential hack M9 was forced into may dissolve entirely, since the
agent is no longer asking itself over the wire.

The payoff is the whole install story:

> **The UI becomes static files inside a Python wheel, served by the
> agent at root. Node disappears from the runtime on every platform and
> for both audiences, and `pip install eugene-plexus` becomes the entire
> product — API and browser.**

Precedent: Open WebUI ships its built frontend inside its Python wheel,
so `pip install open-webui` yields a web UI. This is a known-good
pattern, not an invention.

If the `eugene_plexus_ui` package is absent the agent should serve the
API and say so, rather than fail — `degraded-mode-required` applies
unchanged.

### 3.1 "The UI is going to get much richer — does static still make sense?"

Troy's question, 2026-09-11, and the reason call #1 split in two.

**Static export does not mean a static website.** `output: "export"`
emits a full client-side React SPA. What survives is everything the UI
is made of: hooks and state, client-side routing, code splitting and
lazy loading, WebSockets and SSE, charts, editors, virtualized tables,
drag-and-drop, any npm component library. What is dropped is only the
*server* half of Next — Server Components, Server Actions, middleware,
SSR, ISR, runtime route handlers. **This UI already uses none of them**
(§3), and the one route handler it has is the proxy 1a removes.

**Feature richness is not what static export constrains.** The dominant
pattern for self-hosted admin UIs is a static bundle served by the
backend binary: Grafana, Home Assistant, Portainer, Immich, the Traefik
dashboard. Home Assistant's frontend carries live WebSocket state for
thousands of entities, a drag-and-drop dashboard editor and a card
configuration system — as a static bundle served by Python. Nothing in
this project's roadmap is richer than that.

**The one thing that would genuinely break it** is a secret the browser
must never hold — realistically OIDC's client secret and its
authorization-code exchange, which §10 already names as an SMB gap. But
by this project's own architecture that belongs in `control` or the
agent, which own their config and secrets, not in a Node process
sitting beside them. It argues *for* 1a rather than against it.

**Hence the split.** 1a is architecture and is correct regardless of
what the UI becomes. 1b is a build target: after 1a the UI is a pure
client application either way, `export` and `standalone` differ by one
config line, and the choice is reversible after release. **Do not let
1b block 1a**, and do not treat 1b as a bet on the UI's future.

**One honest caveat, not a recommendation.** Next.js is a framework
built *around* its server; using it with `export` means carrying its
build complexity for the client half alone. If the UI grows as large as
intended, Vite + React Router would be leaner. That is a rewrite and is
not proposed here — recorded only so that if Next starts fighting the
UI later, this is the known alternative and not a fresh discovery.

## 4. Three paths, one artifact

**Path A — developer.** `bootstrap.sh` + the existing `bootstrap.ps1`.
Seven repos, a venv each, editable installs, pre-commit. Uses `git
clone` rather than `gh repo clone` so it needs no authentication.
Audience: contributors.

**Path B — end user, host.** One command:

```
curl -fsSL https://eugeneplexus.com/install.sh | sh
```

which fetches `uv`, creates a venv, installs one meta-package, writes a
service unit, and starts it. Windows gets `install.ps1` doing the same.
Audience: home enthusiasts, **and every GPU box in an SMB deployment**.

Note the prerequisite: **`eugeneplexus.com` currently serves nothing**,
and `specs/README.md:7` already links it. Path B needs somewhere stable
to host the script — the domain, or a raw GitHub URL if the domain is
not stood up first. Either is fine; leaving both undone is not.

**Path C — control plane, container.** A Compose file and one image.
Audience: SMB.

**The three paths ship one artifact shape.** Path C's image is Path B's
install with no GPU and no engines — because the control-plane container
runs an agent too. That is not an accommodation; it is what the
architecture already assumes. `control` is supervised by the local agent
like any other component, components are handed `<KIND>_AGENT_URL`, and
M7's `Runtime.node` / `advertiseUrl` work presumes an agent per host.
A Compose file that ran the four components directly, with no agent,
would be fighting the design.

So the Dockerfile is roughly ten lines over the same `pip install`, and
there is one install to keep working rather than three.

## 5. `uv`, and why not a single binary

**Use `uv`** (Astral). It is a standalone binary that downloads and
manages its own Python interpreter and builds a venv in about a second.
That deletes the worst line in `bootstrap.ps1` — *"Python 3.12 reachable
via the `py` launcher"* — because the installer no longer needs Python
to exist first. It is the 2026 standard for shipping Python
applications and it is the single largest ease win available here.

**Do not ship a frozen single binary** (PyInstaller, Nuitka), however
much Ollama's one-file install is worth envying. The architecture
forbids it: `watchdog-venv-is-runtime` makes the agent's venv the
component runtime, and `default_topology.is_installed()` decides what to
declare by calling `find_spec` against its own interpreter. A frozen
binary has no venv to install into. Ollama can be one file because it is
Go and monolithic; this is a supervisor with a plugin surface.

## 6. Packaging shape

- `eugene-plexus` — a meta-package depending on the five components plus
  `eugene-plexus-ui`. Installing it installs the product. It also
  finally publishes the PyPI stub that has been pending for months.
- `eugene-plexus-ui` — a wheel containing the static export. Built by
  the `ui` repo's own CI (`npm run build` into a wheel), so a UI change
  does not require rebuilding the agent, and located at runtime through
  `importlib.resources`.
- Each component keeps publishing independently, so an operator can
  still compose their own install. That is the expert override.

Version policy, release workflows and who tags what are **not decided
here** and should be settled before the release, not before the install
work.

### 6.1 The gap between §6 and §9, found 2026-09-11 — call #6

**§6 and §9 are in tension and step 3 walks straight into it.** §9 step
3 says `install.sh` "installs the meta-package"; §6 says publishing
that meta-package "finally publishes the PyPI stub"; and §9 puts **the
release last**, behind tool calling. Publishing six packages to PyPI in
order to write an installer *is* the release, in everything but the
announcement — so taking §6 literally would quietly undo the sequencing
decision Troy made deliberately.

**Verified 2026-09-11, so nobody re-checks it:** `eugene-plexus`,
`eugene-plexus-agent`, `eugene-plexus-ui` and `eugene-plexus-gateway`
all 404 on PyPI; `@eugene-plexus/ui` 404s on npm; `agent` has **zero**
GitHub releases. Nothing is published anywhere.

**Recommendation: install from GitHub archives at a pinned ref**, which
needs no registry and no release. `uv pip install
"eugene-plexus-agent @ https://github.com/eugene-plexus/agent/archive/<ref>.tar.gz"`
works today against public repos with no authentication — it is exactly
the mechanism `SPECS_REF` already uses in every consumer, so the
project has run it daily for four milestones. The meta-package then
becomes a small `pyproject.toml` in a repo of its own (or in `specs`)
whose dependencies are those URLs, and **publishing it to PyPI becomes
a one-line change at release time** rather than a prerequisite.

The counter-argument, and it is real: a URL-pinned install is not what
an end user's `pip install eugene-plexus` will look like, so the
installer gets rewritten once at release. That is a small, known,
deferred cost against making the release stop being last.

**Do not resolve this by publishing early.** If it turns out the
installer genuinely cannot work without a registry, that is new
information and it belongs back with Troy, because it moves the
release.

## 7. Linux + NVIDIA — DECIDED 2026-09-11: ship Vulkan, badge it

**Troy's call, taking the recommendation.** Build the `Degraded` plan
described below. The counter-argument is preserved at the end of the
section because it names the failure mode to watch for: if operators
start reporting "it's slow" without mentioning the badge, the badge is
not doing its job and the wall was right.

**The premise was re-verified against upstream on 2026-09-11**, not
taken from the code comment. Today's `b10909` publishes 27 assets:
`win-cuda-12.4-x64`, `win-cuda-13.3-x64` and `win-cuda-13.4-arm64`
exist, and **there is no `ubuntu-cuda` asset of any kind.** The refusal
in `test_linux_with_nvidia_is_refused_not_given_vulkan` rests on a fact
that still holds.

It is narrower than "Linux is unserved", though: `ubuntu-rocm-10.0-x64`
and `ubuntu-sycl-fp16-x64` both exist and `llama_cpp.py:554-557` already
maps them, so **Linux+AMD and Linux+Intel work today.** This is
specifically Linux+NVIDIA — which is the most common serious setup, and
the one where differentiator #1 is currently false.

**Recommendation: install Vulkan, and make the degradation permanent and
visible rather than refusing.** This is `easy-default-expert-override`'s
corollary applied directly — an eager refusal can be wrong, an
explanation of a real failure cannot. Today's behaviour is a dead end
for a non-technical operator, and it predicts an *outcome* ("they will
conclude we are slow") that is better answered by saying so continuously
than by blocking. Concretely: a `Degraded` plan rather than
`Unavailable`; the existing refusal prose becomes a `degradedReason`
carried on the runtime; the UI badges it wherever that runtime appears,
not as a dismissible toast. The source build stays documented as the
expert path.

**The counter-argument, which is defensible and is Troy's to take:**
prompt-processing on Vulkan versus CUDA is not a small delta, and a
badge in a UI the operator may never open is weaker than a wall. If the
refusal stays, it should become *actionable* instead — a verified
source-build script rather than a paragraph.

## 8. macOS — DECIDED 2026-09-11: first-class now, decoupled from MLX

**Recommendation: first-class now, decoupled from MLX.** `macos-arm64`
and `macos-x64` prebuilts ship in that same upstream release, so macOS
is the one platform where engine acquisition works out of the box with
Metal. MLX is blocked on the `upstreamModelId` collision — see
`mlx-engine-unverified.md` — which no amount of Mac hardware fixes.
Tying a working path to a blocked one buys nothing.

macOS first-class means the shell installer runs there, a launchd plist
is written, and llama.cpp acquisition is verified on arm64. **That last
part cannot be verified from the current hardware**, and any claim about
it should say so.

## 9. Build order

**CANONICAL ORDER FOR THE WHOLE ARC.** Revised twice on 2026-09-11:
first after calls #2-#4, then again when **Troy moved the release to
last**, behind tool calling. His reasoning, recorded because it should
survive: *if the project exists to relieve the pain in that thread, the
project as it stands today would fail* — a control plane no agent
harness can use does not answer it. Add to that: **a release is a
positioning event**, and releasing before tool calling announces into
the commoditising space `llama.app` and NVIDIA/Hugging Face just moved
into, rather than the unclaimed one. See
[`agent-clients-and-tool-calling.md`](agent-clients-and-tool-calling.md).

1. ~~**Move the proxy into the agent (1a); ship `eugene-plexus-ui`.**~~
   **DONE 2026-09-11 — see §12.** Both traps §11 named were real: the
   proxy does stream (measured, not asserted), and the browser arc was
   repointed at the agent rather than kept on `next dev`. 1b came out
   **export**, decided at the end as planned.
2. ~~**Windows supervision hardening.**~~ **DONE 2026-09-11, except
   the service integration — see §12.** Graceful stop and port
   diagnosis are built and live-verified; the measurements reshaped
   what the work was. Original note:

   **Windows supervision hardening.** Promoted into the build order by
   call #4: graceful shutdown, port-not-pid process reclaim, a service
   integration. Parity was chosen with this cost visible; it is a work
   item, not an assumption. Sequenced here because step 3 writes the
   service unit that depends on it.
3. **`install.sh` / `install.ps1`** — fetch `uv`, venv, install the
   meta-package, write a systemd unit / launchd plist / Windows
   service, start it. **Read §6.1 first: what it installs FROM is an
   open call and nothing is published anywhere.** The Windows service
   is `pywin32` or NSSM, also open; the hard-kill consequence of
   running as one is settled and badged (§12, step 2). Path B, and also every SMB GPU box. **macOS is in
   scope from the first version** (call #3), including a launchd plist;
   llama.cpp acquisition on arm64 stays unverifiable on current
   hardware and any claim about it must say so.
4. **`bootstrap.sh`** — port the developer script. Small once step 3
   exists, and it shares the prerequisite checks.
5. **Compose file and image** for the control plane. Path C.
6. **Tool calling, end to end** —
   [`agent-clients-and-tool-calling.md`](agent-clients-and-tool-calling.md)
   §5 items 1-2. **The thesis work.** Nothing in that document matters
   until this lands.
7. **Context-window honesty** — that document's §6, and the actual
   differentiator: we launch the engine, so we know the window.
8. **The playground as a diagnostic** — tools, attachments, and the
   `x_eugene_plexus` envelope surfaced, reached over **the same public
   surface a harness uses** (§7.1's trap).
9. **Then** the release.

§7 of this document (Vulkan, decided) is independent of all of it and
slots in anywhere; it touches only the agent's llama.cpp adapter and a
UI badge. The diagnosed-but-unfixed ~2 s post-unload routing window is
likewise independent.

## 10. What this does not solve

Install is not the only thing standing between the project and audience
2. Said here so it is not discovered after the packaging work:

- **Auth is one passphrase plus service tokens.** No SSO/OIDC, no
  per-user identity. M8's metrics are per-request and per-attempt but
  not per-user, so "which department is consuming the GPUs" is not
  answerable.
- **No backup or restore story** for the control root's replicated log.
- **Rolling engine upgrades are unbuilt** (already an open item), which
  matters when inference cannot be taken down during business hours.

None of these block a release. They do mean the honest framing of the
first release is *"audience 1, with audience 2's topology already
proven"* — which is a good story, not a weak one.

## 11. Traps known in advance

- **The proxy streams.** It passes `upstream.body` straight through. The
  Python port needs `httpx.stream` plus `StreamingResponse`, or M10's
  token streaming silently reverts to buffering — which would pass every
  existing check while being broken, exactly the failure family the M10
  acceptance run recorded three times.
- **Deleting the route handler breaks `next dev`.** `m9-acceptance.sh`
  drives a Next dev server, so the browser arc needs either a dev-only
  `rewrites` entry forwarding `/api/proxy/...` to the agent, or to be
  repointed at the agent's own port. Repointing is more faithful to
  production; the rewrite is still wanted for the hot-reload loop.
- **Static export and trailing slashes.** Next emits one HTML file per
  route; serving them from FastAPI needs the trailing-slash convention
  chosen deliberately, or deep links like `/nodes` 404 while the SPA
  navigation to the same page works. A route that works when clicked and
  fails when pasted is the recognisable symptom.
- **`curl | sh` needs to stay auditable.** Publish the script at a
  stable URL, keep it short enough to read, and never have it do
  anything the documentation does not describe.
- **Windows `TerminateProcess`.** `supervisor.py` notes that graceful
  shutdown is a hard kill on Windows, and says plainly that *"Windows is
  primarily a dev surface, real installs are Linux/Mac/Docker."* That
  assumption is load-bearing for a service unit — see the open call
  below, which it is the main evidence for.

### 11.1 Windows — DECIDED 2026-09-11: fully first-class

**Troy's call, and it overrides the recommendation** (a middle tier:
ship `install.ps1`, support single-machine, claim nothing about
multi-host or unattended service). Windows gets parity.

**What that commits, stated plainly so it is not rediscovered as a
surprise:** the installer is the cheap part. Parity means **Windows
process supervision becomes a supported surface**, which is real work
nobody has scoped, and it should be treated as a work item of this
milestone rather than an assumption:

- **`terminate()` is `TerminateProcess` — a hard kill with no graceful
  window.** A supervised engine can leave a GPU context to be
  reclaimed. Needs either a real graceful path or an explicit,
  documented, tested reclaim.
- **Stale processes stack on one loopback port with the oldest still
  serving** — recorded live during M10, where a run read a two-runs-old
  reply. Already survives in the standing rule *kill by port, never by
  pid or command pattern*; as a supported surface it needs to be the
  supervisor's behaviour, not the test harness's.
- **A Windows service integration** alongside systemd and launchd —
  a third one to write and keep working.
- **`supervisor.py`'s own comment now contradicts the product**: it
  says *"Windows is primarily a dev surface, real installs are
  Linux/Mac/Docker."* Fix the comment when the work lands, not before,
  so it does not claim support that does not exist yet.

**The evidence that carried it**, recorded because it is good and will
come up again: audience 1 is substantially Windows — the home
enthusiast with one gaming GPU is the archetype; **Windows+NVIDIA is
the best-served acquisition path in the entire project** (§7 — it is
the only platform upstream publishes CUDA builds for, and it would be
perverse to serve it least well); and every milestone through M10 was
driven from a Windows box.

The original both-ways analysis follows, kept because the middle option
remains the fallback if supervision hardening proves larger than it
looks.

**For dev-surface-only:** `supervisor.py` already asserts it in a
comment that has been load-bearing since M0. Graceful shutdown is a
hard kill, so a supervised engine can leave a GPU context to be
reclaimed. Windows services are a genuinely different integration from
systemd and launchd — a third one to write and keep working. And the
M10 acceptance run recorded Windows stacking three stale stubs on one
loopback port with the oldest still serving, which is the kind of thing
that makes support painful.

**For first-class:** audience 1 is *substantially* Windows — the home
enthusiast with one gaming GPU is the archetype, and telling them to
install WSL2 first is the sort of friction this whole document exists
to remove. Windows is also where llama.cpp's CUDA prebuilts actually
are (§7): Windows+NVIDIA is the **best**-served acquisition path in the
project, and it would be odd to serve it least well. Troy's own box is
Windows 11 and every milestone through M10 was driven from it.

The cost is not the installer — `install.ps1` is cheap next to
`install.sh`. The cost is committing to Windows process supervision as
a supported surface, including the hard-kill behaviour, which is real
work that nobody has scoped.

**The fallback, not taken:** ship `install.ps1`, document Windows as
supported for a single-machine install, and do not claim it for
multi-host or unattended-service use until supervision is hardened.
Retreat to this only with a stated reason — the decision above was made
with the supervision cost in front of it, so "it turned out to be work"
is not a reason.

## 12. Implementation record

Record what was built, what departed from this design, and why, as each
step of §9 lands. **Steps 2-9 are unbuilt; step 2 (Windows supervision
hardening) is the pickup point.**

### Step 1 — the proxy moved, and the UI ships as a wheel. DONE 2026-09-11.

specs `a83df4b`, agent `7cb9c0b` + `4062457`, ui `949e70e` + the e2e
repoint. Verified live by `scripts/ui-hosting-acceptance.sh` — **36
checks, zero failures** — and by `scripts/m9-acceptance.sh`, whose
browser arc now drives the agent instead of `next dev`: **39 checks,
zero failures**.

**What was built.** `eugene_plexus_agent/routes/proxy.py` (the
pass-through) and `ui_assets.py` (finding and mounting the bundle); a
new `eugene-plexus-ui` distribution in the `ui` repo — a hatchling
wheel wrapping the static export, located at runtime through
`importlib.resources`; `output: "export"` with `trailingSlash: true`;
and the deletion of `src/app/api/proxy/[target]/[...path]/route.ts`,
the only dynamic route the application had.

**§3's prediction held: the port is smaller than the original.** The
Next handler's hardest step was resolving a target, which meant calling
the agent's bearer-protected `GET /v1/components` over HTTP — so the
proxy needed a credential of its own in order to look something up. It
is a list scan now.

**M9's two-credential hack dissolved, as §3 guessed it might — and it
was checked rather than assumed.** `x-eugene-plexus-upstream-authorization`
is gone from both sides: the wizard sends the control root's token in
`Authorization` like any other caller. The acceptance run logs in at
the trust root *through the proxy* with one header and reads
`/v1/nodes` with it — the exact call M9 needed two credentials for —
and separately asserts that a request carrying **only** the old header
is refused, so the header is inert rather than deprecated.

**The streaming trap (§11) was real and is cleared, measured rather
than asserted.** 79 content frames through the proxy with the first
token at 20-26% of the request, against 22-25% straight at the gateway.
The comparison is the point: a buffering proxy still delivers every
frame, so a frame count cannot tell the two apart and only a clock can.
The unit test *deadlocks* rather than fails when the implementation
buffers — verified by sabotaging the implementation and watching it
time out — and it calls the route function directly, because
`httpx.ASGITransport` buffers the whole body and would have reported a
correct proxy as broken. That is M10's harness lie in a new costume,
met before it could cost anything.

### Decisions taken during the build

**1b is EXPORT** — decided at the end of step 1, as §3.1 said to, and
on evidence: every route prerendered with no change to any page, the
wheel is 1.7 MB / 129 files, and the whole browser arc passes against
it. One honest correction to §3.1's reversibility claim: `standalone`
is still one config line, but taking it would mean the agent no longer
serves the UI, so it also means a Node process in the runtime and a new
answer to where the proxy lives. The build target is reversible; the
shipping decision it belongs to is not as cheap as "one line" suggests.

**`gateway` resolves by kind, not from `GATEWAY_URL`.** The Next proxy
had an env var with a loopback default. An env var is a second place a
component's URL is written down and a second place it can disagree with
what the agent actually spawned — the OpenClaw trap the driver path had
already avoided. The expert override moved rather than vanished: edit
the topology entry, which was always the authoritative copy.

**Trailing slashes: `true`.** §11's third trap. The export emits one
HTML file per route, and only `out/nodes/index.html` is servable by an
ordinary static file server; `/nodes` then redirects to `/nodes/`.

**The contract gained two path items without operations.** `/` and
`/api/proxy/{target}/{path}` in `agent.yaml`. An operation object must
name a request body, a response schema and a status code, and for a
verbatim pass-through all three are "whatever the component said" — a
generated client would be a fiction. Note that `agent.yaml` had
*claimed* UI hosting in prose since v0.2 while no code did it, and no
path item existed to contradict it; that is how the fossil survived
four milestones.

### Three things that passed while broken, all found here

**A catch-all mount answers for every path, including the API's.**
Starlette takes the first full match and `Mount("/")` matches
everything, so a typo under `/v1/` came back as the UI's HTML 404 page.
Guarded: API-shaped paths always get a Problem document. The one
consequence that cannot be avoided is that a **wrong method** on a real
endpoint is now 404 rather than 405.

**`trailingSlash: true` silently defanged three browser assertions.**
`toHaveURL(/\/$|\/#/)` meant "it navigated away from the form" — and
once every path ends in a slash, `/setup/` and `/login/` satisfy it
too. The arc went green in 2.1 s with a wizard that had not finished
its transaction and a login that had not happened. Only `signIn`'s
token check, which names its own subject, noticed. Fixed with a regex
anchored to the whole URL. **A negative assertion evaluated before its
subject has arrived is the same defect in different clothes**: the
first-run test asserted "not on /setup" immediately after `goto`, which
is true of a page that has not yet decided.

**A test read its own subject off the ambient venv.** The agent's
degraded-mode test made "no UI distribution installed" true by not
installing one — so installing the wheel this step ships turned it red.
It refuses the import explicitly now.

### Left undone, deliberately

`next dev` keeps working through a dev-only `rewrites` entry, because
hot reload is worth keeping; `output: "export"` and `rewrites` cannot
coexist, so both are conditional on `NODE_ENV`. **A dev build therefore
produces no `out/`**, which the staging script checks for and names.
Nothing is published to PyPI — publishing belongs to the release, which
is now last (§9).

---

### Step 2 — children are asked to stop, not killed. DONE 2026-09-11.

agent `b142c76`. Verified live by
`scripts/windows-supervision-acceptance.sh` — **23 checks, zero
failures** — plus 22 unit tests. **The service integration is NOT
built; see "the one open decision" below.**

**Everything in §11.1 was inherited rather than measured, and measuring
it changed the work.** Three hazards went in; one survived, one was
reshaped, one was replaced, and a fourth turned up that nobody had
written down.

**KEPT — `TerminateProcess` is the only stop that skips a child's ASGI
lifespan shutdown.** That is where the gateway closes its metrics
database and the control root closes its log. Measured with a marker
written from inside the lifespan itself, because "it exited 0" is not
the claim:

| how it was stopped                       | rc | lifespan shutdown |
| ---------------------------------------- | -- | ----------------- |
| `TerminateProcess` (today's behaviour)    | 1  | **no**            |
| `CTRL_BREAK_EVENT`, no handler installed  | 3  | yes               |
| `CTRL_BREAK_EVENT`, handler → `SIGINT`    | 0  | yes               |

**The middle row is why this became an agent-only change.** CPython
gives `SIGBREAK` the same default handler as `SIGINT`, so a console
event becomes a `KeyboardInterrupt` and uvicorn unwinds on its own.
**No component needed a line of code.** The estimate going in was a
five-repo edit, and it was wrong by five repos.

**RESHAPED — nothing the agent supervises can stack on a port.** §11.1
carried "stale processes stack on one loopback port with the oldest
still serving" as a supervision problem, from a real M10 observation.
Measured: two uvicorn servers cannot share a port (the second dies with
WinError 10048); `http.server.HTTPServer` can, because it sets
`allow_reuse_address = True`. **Every stacking process in that M10 run
was a test stub.** So the supervisor's job here is diagnosis, not
reclamation: it names the port and the process holding it, and says
plainly that it will not kill it — at boot it cannot tell its own
leftover from a server the operator meant to be running, and killing
the wrong one is unrecoverable where explaining the right one costs
nothing. (The observation was sound, and confirmed by being bitten: an
M10 stub was *still* holding 8195 two days later and silently answered
a probe written to measure something else.)

**REPLACED — a graceful request can be ignored, and a hard kill never
could.** A child that returns TRUE from a console handler outlived the
event by six seconds. The fix therefore *introduces* a hang class, so
every stop now carries an escalation deadline. This hazard exists only
because the other one was fixed.

**THE FOURTH, live on every Windows install and never written down: an
operator restart counted as a crash.** A console-stopped CPython child
exits 3; the supervision loop counted any non-zero exit as a crash. So
every restart bought a back-off sleep, and enough in a row would trip
the crash threshold and drop the component into **safe mode** for doing
exactly what it was asked. POSIX never showed it — SIGTERM gets uvicorn
to exit 0.

**And one more, found by an acceptance check reading the log for
something the API already had:** `_explain_exit` has existed since M0
and its answer only ever reached `Component.lastError`. Every
engine-adapter diagnosis — M4's work included — has been invisible to
an operator watching the console, which is exactly where they are at
boot.

#### Engines honour it too — measured, not assumed

Components are Python and were measured; **engines are third-party C++
binaries and go through the same stop path**, so if `llama-server`
ignored the console event every idle unload would pay the full
escalation timeout before the GPU came back. It does not: a real
`llama-server` holding a 1.8 GB GGUF on the 5090 **exited 0.21 s after
`CTRL_BREAK_EVENT`** with `STATUS_CONTROL_C_EXIT`. No escalation, no
regression to M6's unload timings. vLLM is unverified on this box and
would pay at most the 5 s deadline if it differs.

#### The service decision, and the measurement that constrains it

**A Windows service has no console, and `GenerateConsoleCtrlEvent`
fails there with `WinError 6`** — verified directly by calling
`FreeConsole()` and watching the same call that had just worked stop
working. So **whichever autostart mechanism ships decides whether
graceful shutdown survives into a real install**:

| mechanism                     | console? | graceful stop | cost                                             |
| ----------------------------- | -------- | ------------- | ------------------------------------------------ |
| Scheduled Task at boot         | yes      | **works**     | not a service: no `sc stop`, no recovery policy   |
| Real service via `pywin32`     | no       | lost          | a heavyweight dependency in the one venv          |
| Real service via NSSM          | no       | lost          | a third-party binary in the install path          |
| Real service + `AllocConsole()` | yes     | works         | can reassign the agent's std handles — logs vanish |

We do not conjure a console: an agent whose logs disappear is a worse
outcome than a hard kill.

**DECIDED 2026-09-11 (Troy): a real service, and the hard kill is
accepted.** Row 2 or 3 of that table — call #4 committed to a service
integration as a supported surface, and a Scheduled Task is not a
service. The graceful path still covers the case that dominates
audience 1: a home user running the agent from a terminal, restarting a
component from the UI. What it does not cover is unattended service
operation, and that is a known limitation rather than a fault.

**So it is badged, the way §7's Vulkan degradation is.** The agent
announces at boot how it stops children, as a warning when it cannot do
it gracefully, naming the reason. Discovering it at the first stop
would mean discovering it while something else is already going wrong.
`console_attached()` uses `GetConsoleProcessList` and not
`GetConsoleWindow`, which returns a null HWND under any ConPTY and so
reports "no console" for a process that has one — it was wrong in both
directions on this box and sent one probe run to a wrong conclusion.

**Still open for step 3:** whether the service is `pywin32` or NSSM —
a dependency in the one venv against a third-party binary in the
install path.

#### Two more assertions that matched the wrong subject

Both in the acceptance script, both found by running it:

**A 503 from the proxy and a 503 from an uninitialized trust root are
the same status.** (That one was step 1's; noted here because step 2's
sibling is worse.) **The agent pipes every child's stdout into its own
log with a `[name]` prefix** — so a check for "the agent shut down
gracefully" that grepped the whole log for `Application shutdown
complete` passed against `[gateway] INFO: Application shutdown
complete.` written by an earlier step. The parent's property, asserted
from the child's log. It greps unprefixed now, and the gateway's own
check requires the prefix.
