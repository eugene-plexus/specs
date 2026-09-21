# A4 application workflow acceptance

Run date: 2026-09-21, Windows plus WSL2 Ubuntu. **Implementation is delivered;
the roadmap gate remains open for a user-supplied image.** The image below is a
synthetic preflight, not a substitute for that check. The live NAS and Windows
service were not updated, stopped or reconfigured.

## Versions and isolation

| Part | Measured version/settings |
| --- | --- |
| Claude Code | 2.1.207, native Windows executable; isolated config and disposable Git repository |
| Open WebUI | 0.11.3, Python 3.12.14 on WSL2; separate data directory and local account; actual Chromium UI |
| Engine | llama.cpp b10948, 0.4.0-dev, commit `5f436dddb`, Windows x86_64 CUDA build |
| Model | `lmstudio-community/gemma-4-E4B-it-GGUF`, `gemma-4-E4B-it-Q4_K_M.gguf`, 5,335,291,936 bytes |
| Projector | Same repository, revision `99210a71094c6aa8559f764e0cadedd7d89de94d`, `mmproj-gemma-4-E4B-it-BF16.gguf`, 991,551,840 bytes |
| Runtime | Alias `a4-vision`; 16,384 context; one slot; eight CPU threads; zero GPU layers; projector on CPU; batch 256 / microbatch 128 |
| Eugene | Real agent-supervised gateway, driver and runtime; new temporary state and ports; registered application key; missing credentials return 401 |

Model SHA-256:
`0ffb122c8b6921f13cbc34186e052524d0b5803b17f4867b7197a561400b3770`.
Projector SHA-256:
`bdfc4935857658dfdc8d1adebfa3897c2fec8b3323410f4f73ade36d6efa02be`.
Existing model and engine files were read without modifying them. Zero GPU
layers avoids a new GPU model allocation; the CUDA build may still create a
device context. This run is not a GPU capacity or performance benchmark.

## Task results

| Task | Result and evidence |
| --- | --- |
| Claude Code coding task | **Pass.** Read `clamp.py` and `check.py`, explained the missing lower-bound check, changed `min(value, high)` to `max(low, min(value, high))` using Edit, then ran `python check.py` through Bash. All three checks passed. Five client turns, 219,114 ms; no permission denials. |
| Claude Code follow-up | **Pass.** Resumed the same session, explained below/between/above-bound behavior, reran the check successfully without changing files. Three client turns, 217,651 ms; no permission denials. |
| Normal Claude Code token recipe | **Pass.** Separate non-bare invocation with `ANTHROPIC_AUTH_TOKEN`, local model and isolated config answered `2+2` with `4`; 1,331 ms. |
| Open WebUI chat | **Pass.** Actual browser UI sent `What is 17 plus 25? Answer briefly.`; the model answered `42`, retained in the saved conversation. |
| Open WebUI image preflight | **Pass.** Uploaded a 224×224 red PNG through the attachment control, asked its color, received `Red`; the application saved the image-bearing conversation. |
| User-supplied image | **Pending.** Need a chosen PNG/JPEG and a question with a visibly verifiable answer. No user image was chosen by this run. |
| Cold loading and streaming | **Pass.** Authenticated image request woke the stopped runtime; `swapped_in=true`, reported wake wait 5,338 ms. First response headers at 13.76 s, complete at 15.02 s; streamed `Red`. Both real applications also streamed successfully. |
| Cancellation | **Pass.** In Open WebUI, requested a long list, observed an actively decoding backend slot with eight tokens decoded, pressed the actual Stop button, and observed the slot idle after 187 ms. Timed with a monotonic clock. |
| Text-only target | **Pass.** Removed the isolated runtime's projector, restarted it, observed `image_input=false`, and received HTTP 400 naming the missing vision capability. Restoring the projector restored `image_input=true`. |
| Actionable backend failure | **Pass.** A real image request with more text than the 16K context returned HTTP 400 suggesting a shorter conversation/smaller image and checking the projector/context. The upstream body was omitted, so an echoed image could not leak. Subsequent text inference answered `4`. |

The coding repository allowed only `Read(./clamp.py)`, `Read(./check.py)`,
`Edit(./clamp.py)` and `Bash(python check.py)`. MCP servers, slash commands and
ambient settings were disabled. No stub driver or canned response supplied any
task result. This is one small coding success, not a claim about arbitrary
repositories or the quality of every tool-capable model.

## Measured client requests

The transparent observer forwarded credentials and response bytes unchanged to
the authenticated gateway. It recorded field names, roles, part types, tool
names, status and image-URL SHA-256 only; no credentials or image bodies.

Claude Code sent `/v1/messages?beta=true`, with `model`, `messages`, `system`,
`tools`, `metadata`, `max_tokens` and `stream`; real `tool_use`/`tool_result`
round trips occurred. Bare mode used `x-api-key`; the normal recipe used bearer
authorization. Initially it also sent `output_config.effort: high`, which was
correctly refused. **`CLAUDE_CODE_EFFORT_LEVEL=unset` on 2.1.207 omitted that
unsupported setting and enabled the task.** Declaring custom model capabilities
alone did not remove the effort field. Native Anthropic effort is not implemented.

Open WebUI discovered `/v1/models`, then sent `/v1/chat/completions` with
`model`, `messages`, `stream` and `tools`, using bearer authorization. Its image
message contained ordered `text`, `text`, `image_url` parts; the inline image
URL's SHA-256 was
`c475aa518da421964a08649697bd323efdd2772c1821e44d2ae2cdff00c841b3`.
Separate non-streamed title-generation requests also succeeded. Its built-in
tool definitions were accepted, but the model did not invoke those tools;
RAG, document parsing and every Open WebUI feature are not part of this claim.

## Reproduction and retained evidence

Start `scripts/a4-application-acceptance.py` using the integration Python with
`--engine`, `--model` and `--projector` absolute paths. It creates an authenticated,
isolated workbench, prints its directory and leaves the model cold. Run
`scripts/a4-claude-acceptance.py DIRECTORY --cli PATH_TO_NATIVE_CLAUDE` for the
confined coding task and follow-up. The helper packages the measured task;
review transcripts and the diff, not merely the client's success flag.

For wire observation, run `scripts/a4-protocol-observer.py --target GATEWAY_URL
--host LOCAL_INTERFACE --port UNUSED_PORT --output TRACE_PATH`. The optional
Claude helper `--base-url` points at that observer. A WSL client used the WSL host
interface to reach the Windows gateway; no firewall or live service was changed.

Set up Open WebUI with a new data directory, local account and the workbench's
registered key using the [application guide](../application-workflows.md).
Perform chat, attachment and Stop actions in its UI. Stop only the isolated
workbench with `a4-application-acceptance.py --stop DIRECTORY`; the helper leaves
the empty agent for PID-verified cleanup. Temporary `run.json` and account files
contain secrets and must not be copied into a report or Git.

Local artifacts: `%TEMP%/ep-a4-acceptance-6jthrx_c`: `protocol.jsonl`,
`claude-local.jsonl`, `claude-followup.jsonl`, `claude-auth-token.json`,
`coding-task/`, `webui-chat-record.json`, `webui-image-preflight.txt`,
`webui-cancellation.json`, `image-preflight-sse.txt`, `failure-acceptance.json`.
Open WebUI's isolated state is under WSL
`/home/tcorbin/.cache/ep-a4-webui-data-6jthrx_c`. These are local evidence paths,
not public downloadable artifacts.

## Regression checks

- Windows: agent 956 passed / 4 skipped; control 172 passed; driver 468 passed /
  3 opt-in live skips; library 489 passed / 24 platform/opt-in skips; UI 760 passed.
- Gateway: 483 passed on Windows and Linux, then the additional extreme
  Content-Length regression passed with the 16-test image module. CI covers the
  final 484-test suite.
- Linux: agent 940 passed / 20 skipped; driver initially 465 passed / 3 skipped;
  the final driver revision adds three direct-boundary regressions.
- Python lint, formatting and type checking passed; UI TypeScript, lint,
  formatting and production export passed. A pre-existing library test raced
  its startup scan under concurrent load; it now waits for that scan before
  requesting the fixture scan.
- Image tests cover batch/stream forwarding, fallback skipping text-only
  candidates without dropping images, malformed/remote inputs, MIME and size
  limits, chunked body limits, capability changes, direct CLI refusal, and
  protection against upstream image echo in errors/debug logs.

The published alpha remains unchanged. These are development-build results.

## Delivered component revisions

| Component | Commit |
| --- | --- |
| Contract | `7b1e90622e6aa56397cbf16d8949949f49722322` |
| agent | `486d3c57e9e120374106664345c37e1d6e89698a` |
| control | `855d92378003889d904a662a4008cab9a9451191` |
| gateway | `0659978aeb657588ef8ae7176c4c96a7e87fb2d8` |
| inference-driver | `db335584af141b16e87b9ef76c5baaea64dc1fb4` |
| library | `1e30e54b61bae951cfff9ddf2078a08cb8f081c2` |
| ui | `7a477034da8a78b4e22ca8c1cf65ac215b1bbe5c` |
| ui-source | `3069d1d044083ae4f2d404a57e834df2de1073e6` |

All six exact-revision component workflows passed:
[agent](https://github.com/eugene-plexus/agent/actions/runs/35600975601),
[control](https://github.com/eugene-plexus/control/actions/runs/35600978298),
[gateway](https://github.com/eugene-plexus/gateway/actions/runs/35600981372),
[driver](https://github.com/eugene-plexus/inference-driver/actions/runs/35600985291),
[library](https://github.com/eugene-plexus/library/actions/runs/35600988517), and
[UI](https://github.com/eugene-plexus/ui/actions/runs/35600992840).
The 184 static assets are byte-identical in the source export, distribution
checkout and wheel. Installer isolation and frozen-release artifact checks pass.
