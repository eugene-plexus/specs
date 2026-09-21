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
