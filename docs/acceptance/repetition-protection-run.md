# Repetition protection: initial replay, live pilot and regression checks

Date: 2026-10-03. Local Windows development checkouts; not a deployed release.
Design and configuration: [repetition protection](../design/repetition-protection.md).
Machine-readable data: [replay](repetition-evaluation.json) and
[live pilot](repetition-live.json).

## Replay

The 16-case diagnostic corpus is synthetic, with one case reconstructed from
the reported Qwen paragraphs. It is intentionally small and includes cases
the initial detector cannot solve. At the proposed 100-character/four-copy
threshold it stops four of six loop cases; the two misses are a short primitive
cycle and a passage beyond the 2,048-character maximum. One of ten legitimate
cases would be stopped if enforcement were enabled: an intentional long
quotation repeated verbatim. Its paired Off-override case is preserved.
Consequently the implementation defaults to observation.

The Qwen-cycle replay detects a 377-character period at normalized character
1,536 (about four cycles), delivered at raw character 1,547 with 17-character
input chunks. The remaining 9,763 replay characters are avoided under a
hypothetical stop; this is not measured token or GPU-time savings.

| Threshold | Loop detections | Missed loops | False stops if enforced |
| --- | ---: | ---: | ---: |
| 100 characters × 4 | 4 | 2 | 1 |
| 160 characters × 4 | 3 | 3 | 1 |
| 100 characters × 5 | 4 | 2 | 1 |

On Python 3.12.10/Windows, scanning 114,889 progressing characters in
17-character chunks took a median 11.355 ms and maximum 11.618 ms over seven
runs. These are local CPU measurements without model inference or concurrency,
not service latency guarantees.

Regression coverage includes arbitrary chunk boundaries and Unicode,
whitespace normalization, independent bounded channels, structured-output and
reasoning observation, request overrides, invalid configuration, non-retryable
wire termination, unchanged completed non-streamed output, and an actual
gateway HTTP client closing its response before notifying a slow consumer.
Workbench checks verify that stopped content, reason and chat settings survive
a reload, that no automatic retry occurs, and that a manual retry can disable
the safeguard. The same stop behavior is covered with a real MCP connection,
whose task group wraps stream errors in an exception group.

## Live pilot

The user identified `Huihui-Qwen3.8-27B-abliterated-Q6_K_L`; the running local
llama.cpp server confirmed that exact model and build `b11364-46ca246de`.
All four slots were idle before and after the pilot. Runtime defaults and saved
profiles were unchanged, including `dry_multiplier=0` and `repeat_penalty=1`.

The gateway's `scripts/evaluate-repetition-live.py` sent six serial requests
directly to this engine. Each used seed 42, a 4,096-token maximum and a 90-second
deadline. Other defaults were temperature 1, top-k 20, top-p 0.95, and min-p 0.05.
The three arms were resource limits with observation, the same request with the
gateway detector enforcing stops, and native DRY with request-local
`dry_multiplier=0.8`, `dry_penalty_last_n=2048` (base 1.75, allowed length 2).
This exercises the detector against live inference, not the installed gateway
or Workbench services. Neither the original chat history nor its tools were
available to these requests.

| Prompt | Resource limits only | Detector stop | Native DRY |
| --- | --- | --- | --- |
| Fresh tooling question | Completed, 5.409 s | Completed, 5.308 s | Completed, 6.356 s |
| Intentional 20 copies | Completed, 12.697 s | Stopped, 5.499 s | Completed, 21.878 s |

The fresh question, "What tooling can you see right now?", did **not** reproduce
the reported runaway. Baseline and detector-stop arms produced identical visible
text and completion-token counts (286), with no detection. The answers are not
evidence that the model actually had the tools it described: no tools were sent.

For the deliberate-copy prompt, enforcement detected a 141-character period at
normalized character 576 and closed the stream after 588 visible characters.
The baseline produced 2,838 visible characters and 696 completion tokens. Its
observing detector found the same pattern without interrupting it. Native DRY
also produced repeated passages, with altered whitespace, and used 1,208
completion tokens. This one setting did not eliminate the test pattern.

The interrupted response had no final usage record; token savings are unknown.
The roughly 7.2-second difference from the baseline is a single-run wall-clock
observation, affected by prompt-cache differences and run order. It is not a
representative latency or GPU-compute saving. No arm reached the token or time
limit. Deliberate copies are a legitimate task: this stop is a false positive
for intent, demonstrating the need for the Off override and default observation.

## Validation and remaining evidence

- Gateway: **1,228 passed, 1 skipped**, including 46 repetition-specific tests.
- Workbench backend: **138 passed, 6 skipped**.
- Workbench web: **52 passed** across eight files; production build passed.
- Ruff, formatting, mypy, vendored-contract integrity, ESLint, Prettier and
  TypeScript checks passed in their applicable repositories.
- OpenAPI validation passed; contract sabotage checks caught all 11 cases.

The seven skips concern platform-specific permissions/sandbox behavior and
opt-in Chrome coverage. No installed-service browser acceptance was performed.
The pilot did not deploy the changes. It covers one seed and two prompts;
the original failure, a production false-positive rate, concurrency cost under
load, and any state-of-the-art advantage remain unestablished.
