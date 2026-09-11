# Install paths and distribution

**Status: design, 2026-09-11. Nothing here is built.** Written before any
implementation so a later session can pick it up cold. Every claim marked
*verified* was checked against a repo, a registry or upstream on the day
of writing; everything else is reasoning and is marked as such.

Precedes a release, deliberately. Publishing an installable thing whose
only install is a Windows developer script would bake the gap in.

## Decisions needed before building

Five, all Troy's. Each has a recommendation in the section named, with
the counter-argument that would overturn it. **Answers get recorded
here as they are made**, so this block is the decision log and not just
a question list.

| #     | The call                                                                                      | §    | Recommended                                        | Status     |
| ----- | --------------------------------------------------------------------------------------------- | ---- | -------------------------------------------------- | ---------- |
| **1** | Move the UI proxy into the agent and static-export the UI — **now**, or bundle Node and defer? | §3   | Now                                                | **OPEN**   |
| **2** | Linux + NVIDIA: ship Vulkan with a permanent visible degradation, or keep the refusal?          | §7   | Ship Vulkan, badge it permanently                  | **OPEN**   |
| **3** | macOS: first-class now, or wait for MLX?                                                        | §8   | Now, decoupled from MLX                            | **OPEN**   |
| **4** | Windows: a supported end-user target, or a dev surface only?                                    | §11  | *(no recommendation — see §11)*                     | **OPEN**   |
| **5** | Where `install.sh` is hosted: stand up `eugeneplexus.com`, or a raw GitHub URL first?           | §4   | GitHub URL now, domain before announcing           | **OPEN**   |

**#1 gates the rest** — it decides what every installer installs. #2-#4
are independent of it and of each other. #5 is near-automatic and is
listed only so it is not forgotten at the last moment.

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

## 7. Linux + NVIDIA (open call, recommendation below)

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

## 8. macOS (open call, recommendation below)

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

1. **Move the proxy into the agent; static-export the UI; ship
   `eugene-plexus-ui`.** Everything downstream gets simpler, and this is
   the only step that is real work on the auth path.
2. **`install.sh` / `install.ps1`** — fetch `uv`, venv, install the
   meta-package, write a systemd unit / launchd plist / Windows service,
   start it. This is Path B, and it is also every SMB GPU box.
3. **`bootstrap.sh`** — port the developer script. Small once step 2
   exists, and it shares the prerequisite checks.
4. **Compose file and image** for the control plane. Path C.
5. **Then** the release.

§7 is independent and slots in anywhere.

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

### 11.1 Open call #4 — is Windows a supported end-user target?

**Not a trap but a decision, and the one with no recommendation**,
because the evidence points both ways and the tiebreak is a product
judgement rather than a technical one.

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

A middle option exists and may be the honest one: **ship `install.ps1`,
document Windows as supported for a single-machine install, and do not
claim it for multi-host or unattended-service use** until supervision
is hardened.

## 12. Implementation record

Nothing built yet. This section is the pickup point — record what was
built, what departed from this design, and why, as each step of §9
lands.
