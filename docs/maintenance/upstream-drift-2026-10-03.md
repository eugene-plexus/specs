# Upstream drift audit, 2026-10-03

The day after v0.1.0, every third-party program and service Eugene integrates
with was checked against its current upstream: what our code passes, parses
and expects, against the newest release and its source. Seven parallel reads,
one per integration group. **Nothing was edited, no Eugene component was
started, and no authenticated or paid call was made.** Evidence levels are
marked on every finding:

- **Reproduced**: run here against the real upstream artifact.
- **Source**: read in upstream source at the named tag and in ours at the
  named line.
- **Docs**: from upstream documentation or a changelog only.
- **Reasoned**: inferred from both sides' code, not run.

Scratch evidence (help outputs, source snapshots, changelogs, advisory lists)
is in the session scratchpad and is not kept.

## Fixed the same day

Every finding below was fixed the same day unless it is listed under
**Left open**, with a test that failed before its fix. Where the fix was
live-verified, that is said. The installers pin:

| Repo | Commit | What |
| --- | --- | --- |
| specs (contract) | `31247a9`, `8c41b85`, `678f57f` | `ReasoningEffort.max`; `output_config.format`; Claude Code's four fields; `prompt is too long`; `Input tag`; `namespace` tools; the second truncation test; web_search's other filters |
| gateway | `471447e` | `namespace` tools (live: Codex 0.160.0 spawned a sub-agent through the gateway and got its answer); the Anthropic door's four fixes; the forced search turn retried with `auto`; `blocked_domains`; the second truncation test |
| inference-driver | `971b1db` | see below |
| agent | `ea76998` | see below |
| library | `23a1f89` | three GGUF KV conventions (scalar `sliding_window_pattern`, `shared_kv_layers`, MLA); the 8B starter's shape re-read with them; the Hub note |
| tool-driver | `ed99e7a` | Brave prepaid keys; the pacing wording |
| ui | `f8249d9`, dist `c8d044e` | Claude Code recipe with the model's window, a Codex recipe, an optional address and key for LM Studio and Ollama |
| specs | `ae0304f`…`40210f0` | uv refreshed below 0.12.18; VC++ runtime from `aka.ms/vc14`, at least 14.50; the live checks' retiring model ids; mlx-lm 0.32.0 in the Mac checks; the documents below |

**inference-driver, in detail:**

- **A security hole worse than finding 3: command injection on Windows.**
  npm installs `claude` and `codex` as `.cmd` shims, so their arguments pass
  through cmd.exe. A `"` in a client's system message (Claude) or user
  message (Codex) closed cmd.exe's quoting, and an `&` after it ran a
  command of the client's choosing on the driver host. Reproduced with a
  shim built like npm's.
  - Claude now reads its system prompt from a file of its own
    (`--system-prompt-file`).
  - Codex reads the transcript from stdin (`exec -`).
- **Claude Code runs with no tools:**
  - `--tools ""`, `--permission-mode dontAsk`, `--strict-mcp-config` and
    `--no-session-persistence`;
  - no routing variables in its environment.
- **Codex runs with no tools:**
  - `-c features.<name>=false` for its shell and every other tool. Its
    read-only sandbox blocks writes, not reads, so a shell could print the
    driver host's files to the caller.
  - The configuration file cannot choose Eugene as the provider, or an
    automatic reviewer.
  - `EUGENE_API_KEY` and `OPENAI_BASE_URL` are stripped from its
    environment.
- **Other fixes:**
  - Codex usage is counted once.
  - Current model lists for both CLIs.
  - GPT-6's sampler, `logprobs` and tool rules.
  - **Ollama:**
    - refuses the settings it drops;
    - gets reasoning under the name it reads, and its tool results in call
      order;
    - gets the key on `/api/ps`.
  - llama-server's `:` pings no longer reset the stall clock.
  - **OpenRouter:**
    - `expiration_date` honoured;
    - images on `/api/v1/images`;
    - speech `instructions` and transcription `prompt` refused;
    - `max_completion_tokens` sent.
  - ElevenLabs' probe uses the newest scribe.
  - Kev's model list is read by `id` or `name`.

**agent, in detail:**

- **Linux CUDA:** the CUDA runtime goes beside the server. Live in WSL2 at
  b11375, through the real install path, `--list-devices` went from
  `(none)` to `CUDA0: NVIDIA GeForce RTX 5090`.
- **Newer CUDA minors:** taken only for a card with finished code in that
  build. Per `ggml-cuda/CMakeLists.txt` at b11375, that is compute
  capability 8.6/8.7/8.9, 12.0 and 12.1; any other card gets the 12.x
  build.
- **Rollback window:** `per_page=100` and 24 fallback builds, about a day at
  21 builds a day.
- **Build choices read from the release:**
  - the ROCm version is read off the asset names;
  - Windows arm64 is never asked for `+vulkan`;
  - `linux-arm64-snapdragon` is offered, but not as the default.
- **`parallelSlots` unset** says 4 shared slots.
- **Unset `contextSize`:** the ledger reserves what llama.cpp's fit will
  take.
- **mlx-lm:**
  - a 503 `unavailable` reads as a dead engine;
  - pinned at 0.32.0, so `--adapter-path` takes effect.
- **vLLM:** the install recipes name what 0.30.0 publishes. Every URL was
  checked, and every command resolved with uv.
- **Kev:** `KEV_API_KEY` is carried to the readiness probe and the companion.

## Left open

Each needs a decision, a contract change, hardware, or a live run this
session did not make.

- **Ollama `:cloud` models under "Confirmed local".** They need a per-model
  locality field (`DriverModel` has none), which is a contract change. The
  setting's text now names the gap and `OLLAMA_NO_CLOUD=1`.
- **Operator MCP servers still load in the Codex and Claude Code
  backends' configuration.** For Claude, `--strict-mcp-config` drops them.
  For Codex they still load. They are the operator's own choice.
- **Unknown top-level fields at `/v1/messages`.** Claude Code's four known
  fields are accepted. Anthropic's gateway guide says to accept any field;
  A2's rule says to refuse. A decision.
- **LM Studio's empty 200 on overflow** (lmstudio-bug-tracker#2339). This
  needs the loaded window from LM Studio's API.
- **An Ollama runner that wedges** (ollama#18685). This needs a first-token
  deadline for backends we do not supervise, which is a design question
  against R2.5.
- **llama.cpp memory figures:**
  - The benchmark places the model with `-ngl -1` and no fit, unlike the
    server.
  - A per-device unset-context figure would come from
    `llama-fit-params --fit-print`.
- **Mixed NVIDIA cards:** the contract carries only the lowest compute
  capability.
- **Snapdragon by default** needs OpenCL/Hexagon detection.
- **mlx-lm:** nothing compares an operator's installed version with the pin.
- **Kev:** re-pinning to `kev-1.0` (batching would allow
  `decisionMaxConcurrent` above 1), or serving it through llama-server's
  native `/v1/systemone`.
- **The library's KV estimate:**
  - There is no default sliding-window period when the pattern key is
    absent (gemma3 6, gpt-oss 2). This errs high, and fixing it changes
    common fits.
  - A sliding layer's cache is `window + n_ubatch` padded to 256, and we
    count only the window. That errs low by up to ~200 MiB on a 27B, inside
    the 1 GiB allowance, but low is the direction the module promises
    never to err in.
- **specs scripts:**
  - `responses-acceptance.py` check 3 needs updating for Codex 0.160's
    sandbox policy.
  - `a4-claude-acceptance.py` and `a8-shared-load.py` still set
    `CLAUDE_CODE_EFFORT_LEVEL=unset`.
  - `bootstrap.sh`/`.ps1` still skip uv when one is present.
- **Live runs owed:**
  - Claude Code 2.1.288 against the Anthropic door fixes;
  - the new live-check model ids (`--live`, cents);
  - hosted Claude's forced-tool-choice refusal (the fallback keys on its
    words, from the docs);
  - GPT-6 (docs);
  - Brave prepaid (a third-party capture);
  - Ollama and LM Studio (none on this box).
- **This box's clients:** Codex 0.130.0 and Claude Code 2.1.283 are old,
  and an old client hides new request shapes.
- **Choices made in the fixes, for Troy to confirm:**
  - The Claude Code recipe's `CLAUDE_CODE_MAX_OUTPUT_TOKENS` is a quarter
    of the window below 128k.
  - The 8B starter's shape was re-read (`23a1f89`).
  - An install or update now stops when uv is too old and astral.sh cannot
    be reached.
- **Not ours to fix:** the dated retirements below, and the upstream
  reports listed at the end.

## Versions

| Integration | Verified against | Upstream now |
| --- | --- | --- |
| llama.cpp | b10930 … b11364 | b11375 (2026-10-03); the agent installs the newest build, so this is what users get |
| vLLM | 0.29.0 (2026-09-09) | 0.30.0 (2026-09-22); 0.31.0 tagged 2026-10-02, not published |
| mlx-lm | 0.31.3 (pinned) | 0.32.0 (2026-10-01) |
| Kev | `1c35199` (2026-09-22) | `kev-1.0` (2026-10-01), HEAD `84847f0` |
| Ollama | 0.34.0 | 0.35.1 (2026-09-29); 0.40.0-rc0 makes MLX the default on Apple Silicon |
| LM Studio | never measured (docs only) | 0.4.25 (2026-09-19) |
| Claude Code | 2.1.207, 2.1.283 | 2.1.288 (2026-10-02); `stable` is 2.1.285 |
| Codex CLI | 0.130.0 (2026-05-08) | 0.160.0 (2026-10-01); this box still has 0.130.0 |
| Open WebUI | 0.11.4 (pinned) | 0.11.4, still latest |
| Hugging Face Hub API | live behaviour, 2026-09 | unchanged in every way we depend on |
| uv | 0.12.18 cited | 0.12.22 (2026-10-02) |
| SearXNG | live instance 2026.9.29 | no JSON API change |

## Fix first

These are broken for users today, or a security exposure.

### 1. Every current Codex gets a 400 at `/v1/responses` (Source)

Codex 0.133.0 (2026-05-21, openai/codex PR #23475) moved its sub-agent tools
into one `{"type":"namespace","name":"multi_agent_v1","tools":[…]}` tool. The
`multi_agent` feature is stable and on by default. Custom providers get
`namespace_tools: true` by default (`codex-rs/model-provider/src/provider.rs:63`
at `rust-v0.160.0`), and nothing in config turns that off.

Our door refuses every tool type except `function`, `web_search` and
`image_generation` (`gateway/src/eugene_plexus_gateway/responses.py:422`). So
**every Codex release from 0.133 to 0.160 is refused on its first request.**
Our acceptance runs used 0.130.0, which is older than the change, and so could
not see it.

- **Fix:** accept `namespace` tools by flattening their `function` members.
  Carry `namespace` on the `function_call` item we emit (`responses.py:1307`)
  and read it on input, because Codex routes a call by namespace plus name
  (`core/src/tools/router.rs:258`). MCP servers arrive as namespaces too.
- **Workaround until then:** `[features] multi_agent = false` in the user's
  `config.toml`. This covers only the sub-agent namespace.
- **Instrument:** re-run the Responses door's acceptance with a current Codex.
  Upgrade the box's 0.130.0, which is also too old for the subscription's
  default model.

### 2. A managed Linux CUDA install runs on the processor (Reproduced)

The Linux cudart tarball unpacks into its own folder,
`cudart-llama-bNNNN-bin-ubuntu-cuda-13.4-x64/`, beside the server's
`llama-bNNNN/`. `_install` extracts both into staging and never merges them
(`agent/.../engines/acquisition.py:801-810`). `libggml-cuda.so` finds
`libcudart.so.13` and `libcublas.so.13` only next to itself (RUNPATH
`$ORIGIN`), so the CUDA backend fails to load and llama.cpp falls back to the
processor without saying so.

- **Reproduced in WSL2 at b11375:**
  - With our layout, `llama-server --list-devices` prints `(none)`.
  - With `LD_LIBRARY_PATH` pointed at the cudart folder, it prints
    `CUDA0: RTX 5090`.
- **Same layout at b11010, b11211 and b11364**, so it has never worked since
  Linux CUDA support was built on 2026-09-16. The guest has no system
  libcudart today, so the S10 record's `CUDA0` must have come from libraries
  installed elsewhere at the time.
- **The container is affected too:** its GPU opt-in relies on the same
  install.
- **Windows is not affected:** its cudart zips have no inner folder.
- **Fix:** extract the cudart archive into the server's own folder, or set
  `LD_LIBRARY_PATH` in `default_env`.
- **Check:** use the real tarball layout, and assert after install that
  `--list-devices` names a CUDA device.

### 3. The Claude Code backend runs `claude -p` with no permission mode (Reasoned; security)

`claude_code_cli.py:428-445` passes no `--permission-mode` and no `--tools`.
The child inherits the whole host environment except `EUGENE_PLEXUS_*`
(`_subprocess.py:34-42`).

Claude Code 2.1.285 starts `-p` in **auto mode** "on third-party providers, or
with telemetry off". An inherited `ANTHROPIC_BASE_URL` (our own recipe sets it)
or telemetry switched off would therefore let a prompt from any client key run
Bash or Edit on the driver host, approved by a classifier rather than by a
person.

Not run: whether our case counts as third-party is in minified code. The
hardening is right whatever the answer.

- **Fix:**
  - pin `--permission-mode dontAsk` and an empty or allowlisted `--tools`;
  - add `--no-session-persistence`;
  - strip `ANTHROPIC_*` from the child's environment.

### 4. The installers never update uv; uv had a Windows path-traversal fix (Source; security)

`install.ps1:1860-1861` and `install.sh:1002-1003` skip downloading uv when one
is present. In-app updates re-run the same installers
(`agent/.../updates.py:247-248`), so an install keeps its first uv forever.

GHSA-2cv4-cqwr-gwf7 (2026-09-23): on Windows, uv 0.12.7 to 0.12.17 can write
outside the target directory while unpacking a wheel. It is fixed in 0.12.18,
and there is no workaround. The agent uses that uv to install apps, Open
WebUI's ~245 PyPI packages included (`apps.py:782-799`), and an elevated
install runs as LocalSystem.

- **Affected:** Windows installs first made between 2026-08-27 and 2026-09-22,
  which includes the alpha.1 and alpha.2 testers.
- **Fix:** re-fetch uv when `uv --version` is below a stated minimum (0.12.18).

## Broken under a stated condition

### Claude Code as a client of `/v1/messages`

- **Structured outputs are refused** (Source; found twice, independently).
  - Ours: `anthropic.py:279` and `:775-783` refuse every `output_config` key
    except `effort`.
  - Upstream: Claude Code sends `output_config.format` to any base URL. So
    through Eugene, interactive sessions lose session titles, memory recall and
    prompt hooks; our R4 capture was print mode only and never saw it.
  - 2.1.288 adds `CLAUDE_CODE_DISABLE_STRUCTURED_OUTPUTS`.
  - **Fix:** map `output_config.format` onto the chat path's
    `response_format: json_schema`, which already works. Until then, put the
    variable in the recipe.
- **It does not compact when a local model's window fills** (Source).
  - Upstream: Claude Code compacts after an error only when the message
    matches `prompt is too long` (and two other strings found in the binary),
    and since 2.1.223 it assumes 200K for a model it does not know.
  - Ours: `_Failure.as_anthropic` (`routes/inference.py` ~421) relays the
    engine's own wording.
  - **Fix:** answer 400 `prompt is too long: N tokens > M maximum`, and add
    `CLAUDE_CODE_MAX_CONTEXT_TOKENS` to the recipe.
- **The advisor tool fails every turn** (Docs). Since 2.1.280, Claude Code
  retries without the advisor only when the refusal contains
  `Input tag 'advisor_20260301'`.
  - **Fix:** name `Input tag '<type>'` in our refusal of any unknown server
    tool.
- **Unknown top-level fields are refused** (`anthropic.py:762`; Docs).
  - Upstream: 2.1.288 can add `safeguards`, `speed`, `thread` and
    `diagnostics`, and Anthropic's gateway guide now says not to reject
    unknown input.
  - **Fix:** drop unknown fields and name them in the ignored-settings header.
- **The UI recipe** (`ui/src/lib/clientKeys.ts:121-137`) is behind on three
  counts:
  - `CLAUDE_CODE_EFFORT_LEVEL=unset` is undocumented upstream.
  - Its stated reason is stale: the door has accepted `effort` since
    2026-09-23. `docs/application-workflows.md` repeats the stale reason.
  - It lacks the two variables above.

### Codex, both directions

- **Token counts are doubled** (Source; `codex_cli.py:482-483`). Codex's
  `input_tokens` already includes cached tokens and `output_tokens` already
  includes reasoning tokens.
- **There is no user-facing Codex recipe.** A working one needs:
  - `[model_providers.ep]` with a mandatory `env_key` (PR #39214 stopped
    inheriting ambient auth) and `wire_api = "responses"`;
  - `model_context_window` (Codex assumes 272,000 tokens for an unknown model
    and treats an overflow as fatal);
  - `multi_agent = false` until finding 1 lands.
- **On Windows**, the transcript (Codex) and the system prompt (Claude) go
  through npm `.cmd` shims on the command line (Reasoned). Newlines truncate
  there, and there is an 8191-character limit.
  - **Fix:** `--system-prompt-file` for Claude; `codex exec -` with stdin for
    Codex.
- **Stale model suggestion lists** (`claude_code_cli.py:73-81`,
  `codex_cli.py:78-84`). They only suggest, so this is low priority.

### Ollama and LM Studio (backends the operator adds)

- **We recorded Ollama's default context wrongly** (Source, v0.34.0 and
  v0.35.1 `server/routes.go`).
  - The default is tiered by total GPU memory: under 23 GiB gets 4,096
    tokens; 23–47 GiB gets 32,768; 47 GiB or more gets 262,144, capped at
    the trained length.
  - `agent-clients-and-tool-calling.md:439-441` and
    `context-honesty-run.md:54` say "full trained context".
  - Ollama still drops the middle silently. Our detector
    (`routes/inference.py:3919`, `prompt_tokens × 20 < chars`) cannot see a
    cut to 4k below about 82,000 characters.
  - **Fix:** add a second rule: flag when `prompt_tokens` reaches ~0.9 of the
    `/api/ps` window and `chars/4` exceeds it. Correct both documents. Advise
    `OLLAMA_CONTEXT_LENGTH`.
- **Ollama silently drops `tool_choice`, `top_k`, `min_p` and
  `parallel_tool_calls`** (Source, `openai/openai.go`). We strip them only for
  openai.com (`openai_compat_http.py:350,379,1158`), so a forced or named tool
  choice to Ollama gets prose. That breaks the refuse-don't-drop rule.
  - **Fix:** mark them unsupported for an Ollama source, or extend the
    structured-output repair to it.
- **Replayed reasoning is lost on Ollama** (Source; ollama#18534). We send
  `reasoning_content` (`:3213`); Ollama reads only `reasoning`.
- **`:cloud` models break "Confirmed local"** (Source).
  - Upstream: Ollama forwards them to ollama.com, and `/api/tags` marks them
    with `remote_host`.
  - Ours: `ollama_entry` (`_catalogue.py:297`) ignores that field, and
    locality is per backend.
  - **Fix:** mark remote entries external per model; mention
    `OLLAMA_NO_CLOUD=1` in the locality setting's text.
- **LM Studio can require a bearer token** (since 0.4.0, off by default). The
  add form says "needs no key" and has no token field
  (`ui/src/lib/agent.ts:77`, `BackendForm.tsx:142-145`).
- **LM Studio answers an over-long prompt with an empty 200**
  (lmstudio-bug-tracker#2339, open). Its default context became 8k in 0.4.16.
- **An Ollama runner can wedge on a full cache hit** (ollama#18685, 0.34.4).
  R2.5's rule (a deadline is a 504 that does not cascade) plus a stall timer
  that arms only at the first token means a 600-second hang with no failover,
  for backends we do not supervise.
- **Ollama matches parallel tool results by position, not id**
  (ollama#18762, 0.35.1).
- **Minor:**
  - `_ctx_ollama` sends no `Authorization` (`:3113`).
  - `embeddings-run.md:168` says Ollama ignores `dimensions`; it now honours
    it.

### llama.cpp

- **The newer-minor CUDA rule is likely wrong for Turing, A100 and H100**
  (Source; not run, no such card here).
  - Upstream builds finished machine code for compute capability 8.6, 8.9,
    12.0 and 12.1 only; 7.5, 8.0 and 9.0 get PTX that the driver compiles at
    load. Upstream now publishes only 13.4 for CUDA 13.
  - So a 13.0–13.3 driver on those cards is handed newer PTX than it supports,
    the exact exclusion NVIDIA's minor-version compatibility names.
  - `llama_cpp.py:1250-1268` and `:1404-1416` dismiss it.
  - **Fix:** take a newer minor only where the card has finished code in that
    build; otherwise use the older major.
- **The SSE pings defeat the stall detector above ~31 s** (Reasoned).
  - llama-server sends `:` every 30 s from its HTTP thread, even when its main
    loop is stuck.
  - `openai_compat_http.py:1734` resets the stall clock on any line, and
    `:1768` turns a comment into a "working" frame.
  - Our default of 30 s just beats the ping, but our own error text tells
    operators to raise it.
  - **Fix:** for llama-server, only `data:` lines reset the clock.
- **Settings that show a value other than the one in effect** (Source;
  settings-never-lie).
  - **`parallelSlots`** says `default=1` (`llama_cpp.py:858-875`, and
    `admission.py`). Upstream's `-np` default is -1, which means 4 slots
    sharing one pool.
  - **Unset `contextSize`:** admission reserves 8,192 tokens
    (`admission.py:113`). Upstream's fit starts at the trained context and
    shrinks only until it fits (`common/fit.cpp:270`), so the card is filled
    to the 1 GiB margin while the ledger counts 8k.
  - **The benchmark places differently from the server**
    (`benchmarks.py:107-153`). llama-bench is `-ngl -1` with no fit; the server
    is `-ngl auto` with fit on.
- **The VC++ runtime link is frozen at 14.44** (Source; failure not
  reproduced).
  - Ours: `install.ps1:1401` uses `aka.ms/vs/17`, now the final Visual Studio
    2022 runtime.
  - Upstream: llama.cpp's Windows CPU job builds with Visual Studio 2026
    (14.50+) and is copied into every Windows zip.
  - **Fix:** use `aka.ms/vc14/vc_redist.$arch.exe`, and have `Test-VcRuntime`
    require 14.50 or newer.
- **Minor:**
  - The rollback window: `per_page=30` (`acquisition.py:479`) now spans about
    36 hours, and `FALLBACK_BUILDS=8` about 10 hours, not "about a day".
  - `rocm-10.0` is hardcoded (`llama_cpp.py:1126,1148`).
  - `linux-arm64-snapdragon` is never offered (`:1159`).
  - `+vulkan` on Windows arm64 asks for a build that does not exist.
  - Three GGUF conventions the library does not read (scalar
    `sliding_window_pattern`, `attention.shared_kv_layers`, `kv_lora_rank`).
    Each errs high, which is safe.

### Hosted providers

- **GPT-6 on OpenAI directly:**
  - temperature and top_p cause a 400 (Docs). `OPENAI_FIXED_TEMPERATURE_PATTERN`
    (`openai_compat_http.py:241`) is `^(?:o\d+|gpt-5)`.
  - Astra and 6.1 Sol need the Responses API for tools, but are advertised as
    tool-capable on Chat Completions.
  - Through OpenRouter this is fine.
- **Brave prepaid keys** (all new sign-ups since the free tier ended
  2026-02-12; Docs, third-party).
  - These keys report a monthly bucket with limit 0.
  - `_brave_limited` (`tool-driver/.../providers.py:322-338`) never reads
    `X-RateLimit-Limit`, so a pacing 429 reads as "monthly quota used up,
    resets in about 29 days" and is not retried.
  - **Fix:** skip buckets whose limit is 0.
- **Claude Code's WebSearch on a slot backed by a hosted Claude 5.5 or
  Fable 5.1** probably 400s (Docs).
  - Upstream: those models reject forced `tool_choice`.
  - Ours: our search loop forces `required` on turn 0 (`server_tools.py:1054`).
- **OpenRouter `expiration_date` is ignored** (`_catalogue.py:171`), while
  OpenAI's `shutdown_date` is honoured. 35 listed models carry one.
- **OpenRouter now documents `POST /api/v1/images`.** We post
  `/v1/images/generations`, which still answers.
- **Two fields we send to OpenRouter that it does not document:** speech
  `instructions` (`:1999`) and transcription `prompt` (`:2055`). They are
  probably dropped silently; `speech-run.md:69` says "carried".
- **Smaller:**
  - `ReasoningEffort` lacks `max` (`common.yaml:260`).
  - Responses `web_search` reads only `allowed_domains` (`server_tools.py:178-192`).
  - ElevenLabs `scribe_v1` is deprecated, and our permission probe uses it
    (`elevenlabs_http.py:329`).
  - OpenRouter marks `max_tokens` deprecated in favour of
    `max_completion_tokens`; we send `max_tokens`, which still works.
  - The Brave pacing wording describes a plan new users cannot get.

### vLLM, mlx-lm, Kev (operator-provided environments)

- **mlx-lm 0.32.0 reverses the meaning of a 503 from `/health`** (Source,
  PR #1791).
  - Upstream: 503 `unavailable` now means the generation thread died; while
    loading, 0.32.0 answers 200.
  - Ours: `mlx.py:46-50, 354-356, 377-382, 469-481` read 503 as loading.
  - Harmless at our 0.31.3 pin; a failed load would read as `loading` for
    600 s after a bump. Fix this before bumping, and correct `mlx-engine.md`.
- **`adapterPath` does nothing at 0.31.3** (mlx-lm #1248, fixed in 0.32.0).
- **The vLLM CPU install command 404s for 0.30.0** (Reproduced as a URL
  probe).
  - Upstream: 0.30.0's CPU wheels are `manylinux_2_39`, not `_2_34`
    (vllm#58270), so they also need glibc 2.39.
  - 0.31.0 goes back to 2_34 (PR #58515), unpublished at the time of this
    audit.
- **Stale vLLM install notes:**
  - The PyPI wheel has been CUDA 13.0 since at least 0.28, which needs an
    R580 driver; `vllm.py:565-568` says 12.9.
  - ROCm wheels are `+rocm723` and glibc 2.39; `:576-581` says 7.0 and 7.2.1.
  - XPU has versioned wheels now.
- **Kev at `kev-1.0`/HEAD** (Source):
  - `/v1/models` is now `{models:[{name, …}]}` with no `id`, so
    `systemone_http.py:371-383` returns `[]`.
  - `--host` exists now.
  - The one-request lock is gone; requests are batched up to 64.
  - `KEV_API_KEY`, if set in a runtime's `env`, would 401 our readiness probe
    forever.
  - It requires Python `>=3.12,<3.14`.
  - None of this affects the pinned commit.

## Documents to correct

- `agent-clients-and-tool-calling.md:439-441`, `context-honesty-run.md:54`:
  Ollama's default context (see above).
- `embeddings-run.md:168`: Ollama honours `dimensions`.
- `library/.../hub.py:541-548`, `hobbyist-ux.md:706`: today `full=true` with
  `expand[]` returns `_id, id, downloads, gguf` with sort and filter applied.
  Our code never combines them.
- `mlx-engine.md:33-38`: the "cheaper probe with no change" note.
- `vllm.py` install notes: CUDA 13.0 wheel, `+rocm723`, CPU wheel 2_39 at
  0.30.0, versioned XPU.
- `kev.py:12-19, 72-74, 196-200`, `decision-models.md:45,53`: true at the
  pinned commit, false at `kev-1.0`.
- `c4-open-webui.md:64-66`: "Nothing turns that off". `ENABLE_PLUGINS=false`
  gates tools and functions in 0.11.4. The code interpreter and terminals use
  other paths; that remains unchecked.
- `unraid/eugene-plexus.xml:17-20`, `container.md:183-188`: "nothing is
  released yet". `:v0.1.0` exists.
- `openai-inference-compatibility.md` P5-2: OpenRouter video now takes
  `previous_job_id` to edit or extend a finished job.
- `speech-run.md:69`: OpenRouter speech `instructions` is undocumented
  upstream.
- `application-workflows.md`: the effort-level reason.

## Dates coming up

| Date | What retires | What breaks for us |
| --- | --- | --- |
| 2026-10-09 | OpenRouter's Qwen3 family (`expiration_date`) | slots naming them, with no warning (we ignore the field) |
| 2026-10-20 | `google/gemini-2.5-flash-lite` on OpenRouter | live checks `p2-media-acceptance.py:97`, `p3-audio-acceptance.py:130`; `mistralai/voxtral-small-24b-2507` replaces it |
| 2026-12-01 | OpenAI `gpt-image-1-mini`, `gpt-image-1.5`, `chatgpt-image-latest` | live checks `p4-images-acceptance.py:130,132`; `dall_e` branches are already dead |
| 2027-01-06 | OpenAI `tts-1`, `tts-1-hd`, `gpt-4o-mini-tts-*` | OpenAI-direct speech has no model; the replacement is Realtime-only (P7) |
| 2027-01-20 | `gpt-audio-mini` | live check `p2-media-acceptance.py:100` |
| 2027-02-26 | `whisper-1`, `gpt-4o(-mini)-transcribe(-diarize)` | `/v1/audio/translations` loses its only backend; transcription moves to `gpt-transcribe` (`json` only) |

## Still holds (compact)

- **llama.cpp, release tags:** v-tags still carry no server build (v0.5.0
  carries only `nightly-tag.txt`).
- **llama.cpp, assets:**
  - All 29 server variants and 6 cudart assets match our patterns, and each
    has a sha256 digest.
  - CUDA versions are read from the asset names, and Linux has moved to 13.4.
  - The Windows `+vulkan` merge is still 51 byte-identical files.
- **llama.cpp, flags and output formats:**
  - Every flag we emit is accepted at b11375 by llama-server, llama-bench,
    llama-fit-params and llama-perplexity.
  - `--version`, `error: invalid argument:`, fit's print and llama-bench's
    jsonl formats are unchanged.
- **llama.cpp, readiness:** 503 "Loading model" until ready; `/health`
  `{"status":"ok"}`.
- **llama-server HTTP:** the `/props` builder is byte-identical across
  b11211…b11375.
- **llama-server errors:**
  - A full pool is still 500 "Context size has been exceeded".
  - An over-long prompt is still 400 `exceed_context_size_error` with
    `n_prompt_tokens`/`n_ctx`.
  - A template refusal still starts `Jinja Exception:`.
  - Malformed JSON is now 400 instead of 500 (PR #29060). That is a better
    outcome for us: final, not failed over.
- **llama-server, what we still work around:**
  - A named `tool_choice` is still ignored, so the repair is still needed.
  - `/v1/completions` still drops `suffix`, so `/infill` routing stands.
  - `id_slot` and the slot cache defaults are unchanged.
- **llama-server, fields we read:** `prompt_progress`, `cached_tokens`,
  `reasoning_content`, `/apply-template` and `/tokenize` are unchanged.
- **vLLM:** all twelve curated flags, positional model, `/health`,
  `/version`, `max_model_len`, bind-before-load, both env vars, `reasoning`
  out and `reasoning_content` accepted in.
- **mlx-lm:** the console script and all eleven flags; still no
  `--served-model-name` (PRs #947, #1140 closed unmerged), so the
  `upstreamModelId` split stands.
- **Ollama:**
  - The `/api/ps` window and `/api/generate` raw with `suffix` are
    unchanged.
  - A chat runner still refuses to embed, so the functional probe stands.
  - Tool calls still arrive in one delta.
  - The default bind is still 127.0.0.1:11434, unauthenticated.
- **Codex:**
  - `wire_api` is still `responses` only.
  - Every `exec` flag we pass exists.
  - The `response.failed` codes and retry rules hold, and
    `response.in_progress` is a keepalive.
  - `prompt_cache_key` is still the session id.
  - `external_web_access` behaves as recorded.
- **Claude Code:**
  - `ANTHROPIC_BASE_URL` (no `/v1`), `ANTHROPIC_AUTH_TOKEN` and
    `ANTHROPIC_MODEL` are unchanged.
  - `web_search_20250305` is still its only search tool.
  - The billing line still starts `x-anthropic-billing-header:`.
  - `-p`, `stream-json` and the result envelope are unchanged.
- **Open WebUI 0.11.4:** every environment variable in our entry, `/ready`,
  `open_webui:app` and Python `<3.13` hold. The 19 advisories of
  2026-09-27/28 are all fixed in 0.11.4, which makes 0.11.4 the minimum safe
  version.
- **Hugging Face Hub, downloads and errors:**
  - The 302 with `X-Linked-Size`/`X-Linked-ETag` (= `lfs.oid`) holds, and
    ranges still answer 206.
  - A missing repo is still 401, a gated one 401 with
    `X-Error-Code: GatedRepo`.
  - Rate limits are unchanged.
  - The CDN host moved to `us.aws.cdn.hf.co`; we check no hostnames.
- **Hugging Face Hub, search:** `base_model` is still a list on Qwen repos,
  and `filter=text-generation` still drops a top GGUF repo.
- **OpenRouter:**
  - The listings, `/images/models` descriptors, `/videos` statuses, audio out
    and `cache_control` are unchanged.
  - `/api/v1/systemone` with `typesafe/jev-1.13` is current.
- **Search providers:** Brave's endpoint and header and SearXNG's JSON shape
  are unchanged.

## Upstream features that bear on a documented decision

- **Decision models without a Python environment.** llama-server serves
  `POST /v1/systemone` natively from b11361 (PR #29818: openjev, kev, lev,
  laya, julia-1, nimble, clef, batched). Ollama 0.35 serves it too.
  - Gaps before Kev could ride the agent's own llama.cpp build:
    - llama-server lists models under `data[].id`, not `models[].id`;
    - a clef server answers nothing else;
    - upstream bug #29902 is open.
- **Positioning.** Ollama and LM Studio (0.4.1) now serve `/v1/messages` and
  `/v1/responses` themselves; llama-server has had `/v1/messages`. This
  changes the peer table in `local-inference-control-plane.md`.
- **Cache-aware balancing.**
  - Claude Code always sends `x-claude-code-session-id`.
  - With `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1` it labels each request as main,
    subagent, compaction or auxiliary.
  - `CLAUDE_CODE_MAX_OUTPUT_TOKENS` answers the open item that the budget
    reserves Claude Code's 32,000 `max_tokens`.
- **Codex's real context windows.** Codex's `model_catalog_url` could serve
  it real context windows instead of its 272K guess.
- **Admission.**
  - `llama-fit-params --fit-print on` prints llama.cpp's own per-device
    figures, which could close the unset-context gap.
  - `--load-mode dio` is a candidate for the slow-SMB case.
- **Settings we route away from local engines.** llama-server and Ollama
  accept `reasoning_effort` (including `"none"`), `logprobs` and
  `logit_bias`. P2c routed these to hosted models only, and thinking-off
  could use `reasoning_effort: "none"`.
- **Open WebUI without its own account.** `ENABLE_PLUGINS=false` could let it
  install without an OS account of its own (C4's `localActions: true`).
  Check the code interpreter and terminals first.
- **MLX.**
  - mlx-lm 0.32.0 adds KV-cache quantization (`--kv-bits`).
  - mlx ships Linux CUDA wheels, so MLX being Apple-only is now our choice
    rather than a fact.
- **vLLM:** 0.30.0's `--load-format ipc_cache` keeps weights across restarts,
  which bears on wake cost.
- **OpenRouter:** a Batch API (2026-09-22) for the platform roadmap's batches
  item, and video edit/extend for P5.

## Upstream issues matching our workarounds

- **Named `tool_choice` becomes auto:** ggml-org/llama.cpp#26535 (closed
  stale, 2026-09-17).
- **A system message mid-conversation returns 500:** #27367 (open, not yet
  cited in our records).
- **A restored slot hides a longer cached prompt:** #28276 (open), fix PR
  #28992.
- **The RAM cache restores another conversation:** #27148 (cited); its fix PR
  #27624 is open and not yet cited.
- **Hybrid-model slots livelocking on context checkpoints:** #28280 (open).
  It may be related to the busy-slot wedge.
- **#27361**, which our records call the nearest match to that wedge, was
  closed as not planned on 2026-10-03. **The wedge, and the 6–10 s main-loop
  pause at an LRU slot pick, are still unreported upstream** (Troy's to
  file).
- **`--cache-ram -1` is not unlimited, and hybrid models grow ~640 MiB per
  prompt:** #29324 (PC7).

## Not verified

- No client (Codex 0.160, Claude Code 2.1.288) was pointed at the gateway.
- No Ollama or LM Studio runs on this box.
- No Turing, A100 or H100 card is here.
- No Mac was used, and vLLM was not installed.
- Nothing was executed against llama.cpp b11375 except `--help`,
  `--version` and `--list-devices`.
- The VC++ 14.44 failure is not reproduced.
- The auto-mode trigger in finding 3 is in minified code.
- Brave's prepaid headers come from a third-party issue; Brave's own page
  404'd.
- The Continue, Cline, SillyTavern and Open WebUI recipe keys were not
  re-checked.
