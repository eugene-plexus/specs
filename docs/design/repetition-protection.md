# Repeated response protection

Implemented in the gateway and Workbench working trees on 2026-10-03. The
default is **observe**. Automatic stopping is an explicit opt-in; the replay
results do not justify enabling it for every conversation.

## What is detected

The initial rule looks for four consecutive copies of a passage of at least
100 characters, after collapsing whitespace. Case, punctuation and Unicode
characters are preserved. The two alternating paragraphs reported from Qwen
form one passage. There is no 100-token output cap.

The detector checks every 64 normalized characters and again at a normal
end of stream. A continuing exact loop is detected within 63 normalized
characters after enough copies arrive, plus transport buffering. Patterns
longer than 2,048 characters, approximate repetition, and repetitions of a
short primitive unit are outside this initial rule. Checks that fall just
after a loop ends can miss it; this favors avoiding false stops. A detection
first seen at normal completion is observation-only.

Each channel retains at most `2048 * repetitionRepeats` normalized characters
(8,192 with the default). Reasoning, text, and up to eight independently indexed
tool calls have separate windows. Full string comparisons confirm candidates;
there are no probabilistic matches or unbounded regular expressions. A detector
reports once per channel per model generation. Every server-tool round starts
fresh, so passages from different rounds cannot combine into a detection.

Only streamed visible text may stop. Reasoning, tool arguments, requested
structured output, audio output, non-streamed responses, and text after a tool
fragment in the same model turn remain observation-only. Ordinary Markdown code
or quoted prose is still visible text: four identical long copies can be
intentional, and the detector cannot infer that intention.

Non-streamed calls retain their existing transport and return the complete
answer unchanged; their completed output is observed after the fact. This
does not save generation time. Deadlines and requested token limits remain
the resource backstops, including for missed loops.

## Configuration

The console's gateway configuration exposes these live settings:

| Setting | Initial value | Meaning |
| --- | --- | --- |
| `repetitionMode` | `observe` | `off`, `observe`, or `stop` |
| `repetitionStopModels` | blank | Optional comma-separated exact requested model/slot IDs to stop; others observe. Blank applies the selected mode to every model. |
| `repetitionMinChars` | `100` | Minimum normalized passage length; allowed range 64–2,048 |
| `repetitionRepeats` | `4` | Consecutive copies required; allowed range 3–8 |

An authenticated request can override the mode with
`X-Eugene-Repetition-Mode: off|observe|stop`. This applies to Chat Completions,
legacy Completions, Responses and Messages. Invalid values fail before any
generation. It is deliberately a caller preference, not an operator security
restriction. A caller cannot use it to remove independent token, admission or
time limits. The header is consumed by the gateway, never forwarded upstream.

Workbench's **Chat settings → Repeated response protection** offers inheritance,
Stop, Observe, and Off for intentional repetition. Its value persists with the
chat, including through a manual retry. Clearing it restores gateway policy.

## Stop and cancellation semantics

On a detection eligible for stopping, the gateway closes its owned upstream
stream before delivering the detection-triggering chunk to a slow client. It
then terminates with a specific explanation. Already delivered output remains
unchanged. No retry or model failover follows, and the stop does not count as
backend failure or successful circuit recovery. Request accounting and capacity
release follow the same finalization path as other interrupted generations.

Chat and Completions use an SSE error with `code: repetition_detected` and
`type: repetition_detected`, followed by `[DONE]`. They do not pretend that the
answer finished naturally or fabricate a token count. Responses uses a
`response.failed` event with `invalid_prompt`, and Messages uses
`invalid_request_error`, preserving the non-retryable client behavior already
used for deliberate request termination. Their message explicitly names
repetition. The gateway cannot guarantee a remote provider stops computing
after its connection closes.

Workbench saves the partial answer with status `stopped` and finish
`repetition_detected`, explains why it stopped, and points to the override.
It never automatically retries or executes incomplete tool calls.

The gateway's INFO log records `repetition_detected`, channel, action,
period length, copy count, normalized character position and request ID.
It does not log prompts, matched passages, reasoning or tool arguments.
Stopped attempts retain `RepetitionStopped` in existing request metrics;
observation-only detections are log events, not a new analytics dashboard.

## Backend controls and evaluation

Backend sampling remains model-specific. Eugene already capability-checks
request frequency/presence penalties and local sampling options. A saved
llama.cpp model profile can already carry native launch controls through
**Extra arguments**, including `--dry-multiplier`, `--dry-base`,
`--dry-allowed-length`, `--dry-penalty-last-n` and `--repeat-penalty`, when the
installed binary supports them. Changing launch arguments requires relaunching
that runtime. No universal penalty value is installed by this change.
[Upstream llama.cpp options](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
describe these controls.

vLLM also documents optional token-level repetition stopping. It is a useful
comparison target, but this change does not claim to expose vLLM's
`repetition_detection` through Eugene's provider-neutral request schema.
[vLLM 0.18.2 sampling parameters](https://docs.vllm.ai/en/v0.18.2/api/vllm/sampling_params/#vllm.sampling_params.RepetitionDetectionParams)
are the reference for that backend-specific comparison.

Run `python scripts/evaluate-repetition.py --output report.json` from the
gateway environment. `--corpus captures.jsonl` accepts independently labelled
records with `id`, `text`, `label` (`loop` or `legitimate`), and optional
`channel`, `structured`, `override`, and `variant`. Reports exclude the text.
The bundled diagnostic corpus includes a reconstruction of the reported Qwen
cycle, intentionally repetitive quotations, code, tables, mathematics,
short refrains, reasoning and tool arguments. It compares 100×4, 160×4 and 100×5
thresholds and reports misses as well as false stops.

The [evaluation record](../acceptance/repetition-protection-run.md) includes the
small replay corpus and a live pilot on
`Huihui-Qwen3.8-27B-abliterated-Q6_K_L` with llama.cpp `b11364-46ca246de`.
The fresh tooling question did not reproduce the reported loop. Deliberate
copies demonstrated both cancellation and the intentional-repetition false
positive; one native DRY setting still produced repeated passages. These are
diagnostics, not a representative production benchmark.

To repeat the opt-in pilot against an already-running local llama.cpp server,
run `python scripts/evaluate-repetition-live.py --url http://127.0.0.1:8090
--model MODEL_ID --output live-report.json` from the gateway environment (on
one command line). It runs six serial requests with a 4,096-token maximum and
90-second deadline per request. It changes no saved runtime settings. The
detector runs in the harness around the engine stream; this does not replace
installed gateway/Workbench acceptance. Reports retain counts, output hashes
and short visible previews, without full reasoning text.

Default enforcement requires independently labelled real generations, model
and engine versions, sampling settings and seeds, token/time-limit baselines,
and native controls where the backend supports them. Compare false stops,
missed loops, detection delay, measured tokens/time saved, and concurrent
serving overhead. Replay tail characters are not a GPU compute measurement.
No state-of-the-art performance claim follows from these tests.
