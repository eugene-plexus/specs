# Use a local model from Claude Code or Open WebUI

These recipes target the A4 development build, not the frozen alpha. Update the
agent, gateway and inference-driver together. Create a named client key in
**Home → Use it from your apps**. Use the gateway address shown there; an engine's
own port bypasses Eugene's authentication and routing.

## Claude Code 2.1.207

Choose a model that can call tools. Model quality matters: protocol compatibility
does not make every small model a dependable coding assistant. The acceptance
uses Gemma 4 E4B IT Q4_K_M, llama.cpp b10948, and a disposable Python repository.

Set these variables in the terminal where you launch Claude Code:

```text
ANTHROPIC_BASE_URL=http://YOUR-GATEWAY:8080
ANTHROPIC_AUTH_TOKEN=YOUR-CLIENT-KEY
ANTHROPIC_MODEL=YOUR-MODEL-ID
CLAUDE_CODE_EFFORT_LEVEL=unset
```

Use `$env:NAME = 'value'` in PowerShell, or `export NAME='value'` in bash. The
Anthropic base URL has **no `/v1` suffix**. Claude Code adds `/v1/messages` itself.
For an isolated test, also set `CLAUDE_CONFIG_DIR` to a new directory so your
usual login, plugins and settings do not influence the result.

The `unset` effort value was measured on **2.1.207**: without it the client sends
`output_config.effort: high`, which Eugene refuses. This is not a reasoning-effort
implementation. Newer Claude Code versions need their own check; current upstream
documentation calls the model-default choice `auto`, which is not proof that
older clients send the same wire. [Claude Code environment reference](https://code.claude.com/docs/en/env-vars)

For the minimal `--bare` mode, use `ANTHROPIC_API_KEY` instead of
`ANTHROPIC_AUTH_TOKEN`: that mode explicitly requires an API key and skips
keychain access. The acceptance additionally disables adaptive thinking with
`CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1` and `MAX_THINKING_TOKENS=0`, sets
`CLAUDE_CODE_MAX_CONTEXT_TOKENS=16384` and
`CLAUDE_CODE_MAX_OUTPUT_TOKENS=2048`, and offers only `Read`, `Edit`, and `Bash`.
Use your model's actual context window, shown in Eugene's model listing.

Start in a disposable repository. For a two-file test, allow reads of only
`./clamp.py` and `./check.py`, edits of only `./clamp.py`, and the exact shell
command `python check.py`. Keep normal tool permissions enabled. Inspect the
result, run the check, and then ask a follow-up in the same session. Eugene
transports tool calls and results; Claude Code executes the tools on its host.

## Open WebUI 0.11.3

In **Admin Panel → Settings → Connections**, add an OpenAI-compatible connection:

```text
URL: http://YOUR-GATEWAY:8080/v1
Key: YOUR-CLIENT-KEY
```

Open WebUI discovers models from that endpoint. Pick the model in a new chat and
send a short text question first. If Open WebUI runs in a container or WSL,
`127.0.0.1` refers to that environment; use an address it can reach. Do not expose
the unauthenticated engine to solve a gateway-address problem.

For pictures, load a supported vision model and its **matching mmproj GGUF**
from the same model repository. In Eugene's llama.cpp runtime/profile settings,
set **Vision projector** to its path on the inference node. **Run vision projector
on CPU** is optional. Projector paths are local to that node; Eugene does not
automatically copy or map them from a NAS. Start the runtime and check
`x_eugene_plexus.image_input: true` in the gateway's `/v1/models` response.

Eugene's built-in Playground attachment control still accepts text files only.
Use **Open WebUI** for this image workflow.

Attach a PNG or JPEG using Open WebUI's attachment control and ask a question
whose answer is visible in it. If Open WebUI's model settings have Vision
disabled, enable it for this confirmed vision model. The initial implementation
supports llama.cpp's single-model server with a loaded projector; merely choosing
an HTTP provider or a GGUF marked vision does not establish support.

Keep attachments within the [image limits](api-compatibility.md#image-input-a4).
Earlier images remain in the conversation and count toward the limits. Resize
large images before attaching them. Remote image URLs, animations and non-PNG/JPEG
files are refused; a text-only fallback cannot silently answer without the image.

Open WebUI's Stop button cancels its active generation. If an error says the model
is not ready, use Eugene's Inference page to inspect the runtime. If the backend
refuses an image request, check the matching projector and context window, then
try a smaller image or shorter conversation. Native Anthropic reasoning, audio,
document parsing, RAG and all built-in Open WebUI tools are outside this recipe's
compatibility claim.

See [the A4 acceptance record](acceptance/a4-application-workflows.md) for exact
tasks, artifacts, results and the completed user-image check.

For shared use, consult the [tested configurations and support boundaries](support-matrix.md).
An Open WebUI connection normally uses one Eugene application key for its users;
Eugene's limits and usage attribution apply to that key, not to each WebUI login.
Budget concurrent application keys against the runtime's slots and test your own
model/context/workload before increasing limits.

## Typed decisions with Kev (experimental, B2)

Eugene's `POST /v1/systemone` speaks the TypeSafe System One protocol: one
`state` and named `noul`/`choice`/`score` questions in, structured probabilities
out. Your application decides what to do with the answer; Eugene never acts on
it. This is on `main` toward alpha.3 and **not in alpha.2**. It was measured on
WSL2 CPU only ([the B2 run](acceptance/decision-run.md)); see the
[API boundaries](api-compatibility.md#typed-decisions-b2).

**1. Make Kev's environment.** Kev is its own Python project, never installed
into Eugene. On the inference node (Linux or WSL2; native Windows is untested
upstream), clone the commit Eugene is pinned to and sync it with uv (Python 3.12
or newer):

```text
git clone https://github.com/jaredpalmer/kev.git ~/eugene-kev
cd ~/eugene-kev && git checkout 1c351992ba3df4a0a0f2ae03051b25466a2c7bcb
uv sync --extra serve
```

In **Config → Agent**, set `kevPython` to that checkout's interpreter
(`~/eugene-kev/.venv/bin/python`). Use the engine's own setting: a uv venv's
`python` is a link to a shared interpreter, so adding the venv to
`engineBinaryRoots` does not whitelist it. The Inference page's engine list
reports Kev as found once the interpreter can import `kev.serve` and torch.

**2. Get the checkpoint.** The measured starter is `jaredpalmer/kev-0.8b` at
revision `54f4f8777356cd5bbbb6c6919c657f26e6f2f6d8` (Apache-2.0; base model
`Qwen/Qwen3.5-0.8B-Base`). Eugene's Library recognizes a Kev checkpoint by
`head.pt` beside `adapter_config.json`. The first launch downloads the base
model into the node's Hugging Face cache, so it needs network access and can
take minutes. Later launches can run with `HF_HUB_OFFLINE=1` in the runtime's
environment; the run proved that relaunch at 4.5 s.

**3. Launch it.** The measured path declares the runtime on the node's agent
with an operator token (`POST /v1/runtimes`):

```json
{"name": "tickets", "engine": "kev", "modelPath": "/path/to/kev-0.8b", "modelAlias": "tickets"}
```

The agent starts `python -m kev.serve` bound to loopback and adds a companion
driver that serves one decision at a time. Add `"env": {"CUDA_VISIBLE_DEVICES": ""}`
to keep it off the GPU. Only CPU has been measured; CUDA, ROCm and Metal are
unverified. One-click **Run** from the Library has not been exercised for Kev.

**4. Ask it.** Use a client key from **Home → Use it from your apps**. The
Playground shows a **Decisions** panel whenever a model lists the `decisions`
surface, with a sample ticket and a copyable request. The same request by hand:

```text
curl http://YOUR-GATEWAY:8080/v1/systemone \
  -H "Authorization: Bearer $EUGENE_PLEXUS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model": "tickets",
       "state": {"subject": "Charged twice", "body": "I was billed twice for order A-1."},
       "questions": {
         "refund": {"type": "noul", "instructions": "Is the customer asking for a refund?"},
         "team": {"type": "choice", "instructions": "Which team should handle this?",
                  "criteria": {"billing": null, "shipping": null, "technical": null}},
         "urgency": {"type": "score", "instructions": "How urgent is this?",
                     "criteria": ["not urgent", "soon", "today", "immediately"]}}}'
```

The run's real Kev answered a refund question like this with `noul` 0.98 and
routed it to billing. On CPU one question took 228 ms at p50. A single-slot Kev
answers 503 while it is busy; retry later rather than in a loop.

**The TypeSafe Python SDK** works by changing its base URL to the gateway and
using an Eugene client key. Set `max_retries=0`: a retried decision is a second
decision. Install the SDK from TypeSafe's own instructions and pin the version
you test. **`pip install typesafe` installs an unrelated package** (PyPI's
`typesafe` stops at 0.9.1; measured 2026-09-22), so the SDK half has not been
tested here. curl is the verified client.

### Register another System One server

Any server that answers `POST /v1/systemone` in the pinned shape can sit behind
Eugene. Add an inference driver with provider **Custom System One URL**
(`systemone_custom`) and either `runtimeName` (a runtime this install supervises)
or `baseUrl` (anything else; the driver appends `/v1/systemone`). Set
`decisionMaxConcurrent` to how many requests the server can hold, so the gateway
never over-admits it, and `apiKey` if it wants a bearer token.

Set `backendLocality` to `local` only for a server you know runs on your own
machines. Only a confirmed-local backend serves local-only client keys; unknown
is treated as external.

The server's answers must pass the driver's checks, or the caller gets a 502
naming the defect:

- every question in the request answered, and no others;
- each answer's `type` matches its question;
- `noul` and `confidence` are finite numbers in [0, 1];
- `choice` is one of the request's own options, with `probabilities` over those
  options summing to 1 (within 0.05);
- `score` lies inside the request's scale, with `probabilities` and `legend`
  naming only its levels (`"0"` for the first level).

Before trusting a server, send it the curl request above and one question of
each kind with your real data. Eugene checks shape, not accuracy.

### Hosted Jev (unverified)

Provider **TypeSafe (hosted Jev)** (`typesafe`) sends decisions to
`https://api.typesafe.ai` with your TypeSafe `apiKey` set on the driver, never
in the client request. It is always external: local-only keys are refused before
any state leaves the machine, and it is never used as a fallback for a local
model. It has passed fixture tests only. No credentialed request has been
recorded, so do not rely on it until one has.
