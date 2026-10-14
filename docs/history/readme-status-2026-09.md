# Historical README status — September 2026

Archived from the [README at `7b9c137`](https://github.com/eugene-plexus/specs/blob/7b9c137cef66fb59ae40a001f6654bb48c6bab57/README.md)
on 2026-10-14. The section below was labeled 2026-09-17 and includes later
annotations. Its wording is retained, with relative links adjusted for this
location. It is a historical development record, not a list of current defects
or support promises.

For the current release, see the [project overview](../../README.md#current-status),
[release notes](../releases/v0.2.1.md) and [support matrix](../support-matrix.md).
The [release roadmap](../design/release-roadmap.md) records the subsequent fixes.

## Historical snapshot — 2026-09-17

The following snapshot predates R1-R8 and the alpha; its defect and publication
statuses are historical, not the current pickup list. Their implementation
records are in the [previous roadmap](../design/release-roadmap.md).

As of **2026-09-17**, this is a pre-1.0 control plane under active development, and **not yet releasable — deliberately**. Milestones M0 through M11 are built, each with a re-runnable acceptance script rather than a claim, and so are ten further slices since (the resource-tree UI, Library folders, the hobbyist onboarding plan, Issues, a node-local model copy). Installers, a developer bootstrap and a control-plane container image exist; the container image is published to GHCR as `:edge`, and nothing else is published — no GitHub Release, nothing on PyPI or npm.

**An adversarial code review on 2026-09-17 found 38 anchored defects plus an architectural note, 11 of them rated High for a public first release.** Eight are being fixed before any public link and five more before the first hostile review; the order is [`docs/design/release-roadmap.md`](../design/release-roadmap.md). Until they land, **do not expose this to a network you do not control** — the login rate limiter can be driven from a request header when the browser reaches it through our own proxy, which is a pre-authentication defect. (A second one needs an operator token first: a crafted single-file download spec can write outside your model folders.)

- **Live-verified on real hardware:** llama.cpp *and* vLLM supervision, model scanning and profiles, catalogue search and resumable downloads, replica balancing, priority-tier failover, idle unload, wake on demand, memory admission, retained per-request metrics, tool calling end to end, embeddings, real token streaming, and a node keeping its own copy of the models it runs (21 s to serving against 266 s over SMB).
- **Multi-host is proven on two real machines** (Windows + WSL2 Ubuntu, across NAT and a host firewall): non-loopback binds, derived advertise addresses, a cross-host completion, an idle unload decided on one host and executed on the other, and a full signing-key rotation. A NAS-hosted library serving a 27B to a GPU node is the live install. **Not proven: two replicas of one model on two machines** — the gateway keys runtimes by bare name, so that case cross-wires today (roadmap R1.6).
- **Hardware-aware quant guidance is built and is not yet trustworthy.** Two code paths compute a fit and only one carries the per-layer KV arithmetic, so the number the one-click Run path writes into a profile can be far smaller than the one the recommendation card showed (roadmap R1.3). A Windows machine with an AMD or Intel GPU is currently detected as having no GPU at all and is given a CPU-only engine build (roadmap R2.3).
- **The browser path is verified**, as of M9: Playwright drives first run, login, restart-on-login and the topology-resolved proxy against a live install; `scripts/hobbyist-acceptance.sh` counts real clicks from a clean guest to a first token on Windows and WSL2.
- **Still unverified:** a signing-key rotation with a genuinely offline node, a partitioned-but-alive old control root, two-GPU placement, macOS on bare-metal hardware, and concurrent users against one runtime. **macOS and MLX are verified on GitHub's (virtual) Macs** (A4, 2026-09-30: the installer, launchd, MLX and llama.cpp on Metal); MLX is no longer experimental. Clock skew is no longer unverified — it took a worker out of the live install on 2026-09-15, and every component now tolerates five minutes of it.
- **Provider compatibility is a subset.** Anthropic `/v1/messages` is implemented for text/tool clients, with explicit limitations. Images are planned in A4; Responses API parity is not promised. See [API compatibility](../api-compatibility.md).
- **Known gaps:** rolling engine upgrades; a mixed-version engine fleet is possible and nothing detects it; no structured model-slot editor; one control-root screen (`/nodes`). The ~116 ms of control-plane overhead measured at M8 **is explained** — a fresh HTTPS client per request, parsing a CA bundle on the event loop — and is the first fix on the roadmap.

Records: [the node-local copy](../acceptance/model-copy-run.md) ·
[Library folders](../acceptance/library-folders-run.md) ·
[the hobbyist click budget](../acceptance/hobbyist-run.md) ·
[Issues](../acceptance/issues-run.md) ·
[M7 on two hosts](../acceptance/m7-two-host-run.md) ·
[M4 vLLM](../acceptance/m4-vllm-run.md) ·
[M8 metrics](../acceptance/m8-metrics-run.md).
Deploying over a tailnet: [`docs/deployment/tailnet.md`](../deployment/tailnet.md) ·
in a container: [`docs/deployment/container.md`](../deployment/container.md).
