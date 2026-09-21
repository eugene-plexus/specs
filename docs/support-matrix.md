# Tested configurations and support boundaries

This matrix describes development evidence as of 2026-09-21. The published
`v0.1.0-alpha.1` remains a frozen earlier build; use its
[release notes](releases/v0.1.0-alpha.1.md) for that build's limits. A passing
fixture or one owner's machine is not platform certification.

**Measured** means a real process/device performed the stated task.
**Simulated** means automated fixtures supplied platform or hardware facts.
**Pending** means the implementation exists but the named physical check is
missing. **Unsupported** means the current product does not provide that path.
These labels apply to individual promises, not an entire operating system.

## Installation, engine and startup

| Configuration / promise | Evidence | Boundary |
| --- | --- | --- |
| Windows x64, Python 3.12, installed console agent, CPU llama.cpp | **Measured:** isolated installation, actual downloads and browser replies in [S10](acceptance/s10-download-run.md) and [A1](acceptance/a1-home-readiness-run.md). | Existing Windows host; not a clean OS or every CPU. |
| Windows x64, current component source, CPU llama.cpp, shared applications | **Measured:** [A8](acceptance/a8-shared-load-run.md), Ryzen 9950X / 93.56 GiB RAM, Gemma 4 E4B Q4_K_M, 5 slots / 16,384 context each. Chat p95 3.73 s alone and 9.25 s in the declared five-client mix; coding tasks passed. | Finite burst, 12 chats per scenario; not sustained load. CPU inference; no generic five-user or GPU capacity promise. |
| Windows x64 + RTX 5090, llama.cpp CUDA | **Measured:** [hobbyist acceptance](acceptance/hobbyist-run.md), plus the owner's successful service inference and 70K-context profile benchmark. | Historical build/owner observations; not a current shared-load GPU benchmark, nor evidence for an 8 GB card. |
| Windows LocalSystem service registration, companion startup, stop | **Measured:** isolated Windows CI service checks and [A7 final CI](acceptance/a7-recovery-run.md); owner's migration and subsequent inference also succeeded. | CI host and owner observations are distinct; neither proves boot-before-sign-in on every machine. |
| Windows reboot before sign-in, credential availability at boot, session-0 engine shutdown, network storage and tray control | **Pending** for the complete physical acceptance sequence. [R2.6 procedure](acceptance/windows-service-run.md) lists the checks. | Successful migration, restored two-way connectivity and inference remain accepted observations. A coordinated reboot and actual storage/tray actions require the owner's participation. |
| Linux x64 in WSL2, installed console agent, CPU llama.cpp | **Measured:** [A1](acceptance/a1-home-readiness-run.md), [S10](acceptance/s10-download-run.md) and recovery/refusal checks. | WSL is not a native Linux boot test. |
| WSL2 + RTX 5090, llama.cpp CUDA | **Measured:** [hobbyist run](acceptance/hobbyist-run.md), with actual Linux CUDA acquisition and first reply. | Historical engine/build evidence; no current five-client GPU capacity measurement. |
| Native Linux systemd startup before login using lingering | **Pending** physical boot verification. Installer/service configuration has automated coverage. | A running WSL systemd user manager does not establish an unattended native Linux reboot. |
| Linux amd64 container control plane | **Measured:** Compose acceptance and [A7 restore](acceptance/a7-recovery-run.md), including real CPU inference after replacement. | Isolated Docker CI; NAS mounts, host networking, secrets and permissions remain operator-specific. Container control plane does not automatically use the Windows GPU. |
| Apple Silicon native and Rosetta-started installation; Metal inference; launchd startup | **Simulated** interpreter-selection and installer cases; **pending** physical Mac checks in [R3.7](acceptance/native-apple-python-run.md). | No physical Mac acceptance available; do not advertise verified Mac operation. |
| Intel Mac / Linux ARM64 | Platform selection exists; **pending** representative installation/inference/startup acceptance. | No transferable pass from x64 or Apple Silicon fixtures. |
| AMD/Intel GPU detection and Vulkan selection on Windows | **Simulated** probing/selection coverage in [hardware visibility](acceptance/unseen-card-run.md). Physical inference and concurrency remain **pending**. | Detection is not successful engine execution. No verified Windows SYCL path is claimed. |
| Modest 8 GB GPU / 16 GB RAM capacity | **Simulated** scoring of the shipped starter set in [S10](acceptance/s10-download-run.md#the-8-gb-gpu--16-gb-ram-starter-check); **pending** physical workload measurement. | A fit estimate does not establish response time, concurrency or reliable startup. |
| User-installed vLLM | Existing supervision/integration; current model-specific shared-load, request admission and restore of its external environment are **pending**. | A7 backs up Eugene, not an arbitrary external Python/CUDA environment. |
| MLX through the current distribution | **Unsupported.** Experimental work is separate from the shipped main branch. | Do not infer support from an Apple hardware label. |

## Applications, policy and recovery

| Promise | Evidence / limits |
| --- | --- |
| Claude Code 2.1.207 via Anthropic Messages | **Measured:** [A4](acceptance/a4-application-workflows.md) completed a confined edit/check and follow-up with local Gemma 4 E4B. Effort must be omitted as in the [recipe](application-workflows.md). Not native Anthropic reasoning/caching or arbitrary coding-task reliability. |
| Open WebUI 0.11.3 via OpenAI chat | **Measured:** actual browser chat, user PNG, streaming and Stop in A4. Image input requires a matching projector and confirmed backend capability. RAG, audio, every built-in tool and newer app versions are not established by that run. |
| Key revocation, scopes, concurrency/rate limits and local-only routes | **Measured:** isolated signed multi-component runs in [A3](acceptance/a3-client-keys-run.md), [A5](acceptance/a5-scoped-keys-run.md), [A6](acceptance/a6-local-only-run.md). App keys are not end-user identities inside Open WebUI. Limits are per key across accepting gateways; do not add unrestricted keys and assume a global engine queue bound. |
| Conservative failover and cancellation | **Measured:** [A6b](acceptance/a6b-failover-safety-run.md) real gateway/driver processes with controlled HTTP/CLI failure fixtures. Ambiguous work is not automatically replayed. A cancelled remote request is not proof that a provider stopped computing. |
| Recovery after a failed update | **Measured:** [A7](acceptance/a7-recovery-run.md) Windows and container replacement, authentication, profiles, policy, revocations and a real completion. Use the [public recovery guide](https://eugeneplexus.com/recovery/). Manual service registration, same OS/architecture, accessible recorded assets and online package reconstruction are required. |
| Stable business production readiness | **Not established.** Limited pilot evidence is distinct from certification, HA, disaster recovery across every topology or a universal capacity guarantee. |

## Choose a pilot configuration

Keep one gateway address in the applications while Eugene supervises the model,
checks credentials, applies key limits and routes requests to eligible backends.
Use a named key per application, set model/locality permissions deliberately,
budget all keys against the engine's slots, and rehearse recovery before updates.
Begin with one client and measure the actual prompts/model/context you intend to
share before raising concurrency. The profile benchmark measures decode speed
at context depths; it does not replace an application load test.

Moderated friend sessions remain open, independently of automated acceptance.
Record failures against the exact tested version and reassess the supported
audience before another release; completion of development work is not release
authorization.
