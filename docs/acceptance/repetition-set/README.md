# Row 19 labelled repetition evaluation

Recorded on 2026-10-21 in the `r19-repetition-default` worktrees. No live model
or installed service was called. The gateway detector is imported from the
gateway worktree's own environment.

`cases.jsonl` is the evidence: 56 independently labelled cases, each with an ID,
label, reason, origin and SHA-256 of its exact UTF-8 text. Labels describe
unwanted looping versus requested repetition; factual correctness is separate.
The labels were assigned before the threshold sweep. Requested copies are
legitimate and count as false positives when stopped.

| Origin | Loops | Legitimate |
| --- | ---: | ---: |
| Complete recorded answers from `a5-data` | 5 | 23 |
| Recorded visible prefixes from `repetition-live.json` | 0 | 2 |
| Constructed examples and boundary cases | 7 | 19 |
| Total | 12 | 44 |

Real records carry their source file and JSON pointer, model, engine, sampling
settings and seed where available. `scripts/test_evaluate_repetition_set.py`
checks the text against those artifacts. The five real loops are all available
visible answers in `a5-data/required` with sustained unwanted prose or emoji
cycling. They ended at the 4,096-token limit. The 23 legitimate complete answers
are all distinct visible answers of at least 200 characters in the top-level
`a5-data/*.json` files. Exact duplicate text is included once. These answers
include progressing lists and tables. An answer need not be factually correct
to be a negative example for repetition stopping.

The original captures include non-streamed answers. The script replays their
exact visible text as eight-character stream events, so their results describe
what **would** happen on a streamed request. It does not claim those historical
requests were interrupted. The two pilot prefixes are explicitly partial;
their missing tails are not invented or scored. The reported two-paragraph
Qwen cycle is a **constructed reconstruction**, not a captured generation.

Constructed legitimate cases cover numbered lists, blank and populated tables
(including a nine-column grid), repeated code lines and blocks, short and long
poem refrains, plain-text JSON arrays of identical numbers and records, and
finite verbatim quotations. Reasoning, tool arguments and requested structured
JSON add three observation-only cases. Thus the serving precision denominator
includes 41 eligible legitimate answers; all 44 must pass under the built
default. The seven constructed loops include whitespace changes, the reported
cycle, short primitive units, approximate cycles and the detector's passage
length boundaries. Random boundary text uses seed 19 and is stored literally.

Run from `specs`:

```powershell
../gateway/.venv/Scripts/python.exe scripts/evaluate-repetition-set.py --output docs/acceptance/repetition-set/report.json
../gateway/.venv/Scripts/python.exe scripts/evaluate-repetition-set.py --sweep --output docs/acceptance/repetition-set/sweep.json
../gateway/.venv/Scripts/python.exe -m pytest scripts/test_evaluate_repetition_set.py -q --basetemp=tmp-row19/specs-test -p no:cacheprovider
```

The sweep tests minimum passage lengths 64, 80, 100, 128, 160, 200, 256, 384,
512, 1,024, 1,600 and 2,048, each with 3, 4, 5, 6 and 8 copies: 60 policies.
`report.json` records the 100 × 4 candidate; `sweep.json` records every policy
and every case's outcome. The actual default policy is reported separately
from hypothetical Stop policies. `--fail-on-false-stop` deliberately exits 1
for the 100 × 4 candidate: five requested answers would be stopped. It does
not silently remove requested copies from the decision.

| Stop policy | Loops caught | False stops / eligible legitimate | Precision | Recall |
| --- | ---: | ---: | ---: | ---: |
| 100 × 4 | 6 / 12 | 5 / 41 | 54.5% | 50.0% |
| 100 × 8 | 6 / 12 | 3 / 41 | 66.7% | 50.0% |
| 160 × 4 | 5 / 12 | 1 / 41 | 83.3% | 41.7% |
| 384 × 4 | 2 / 12 | 0 / 41 | 100% | 16.7% |
| 2,048 × 4 | 1 / 12 | 0 / 41 | 100% | 8.3% |

Precision is caught loops / all stops. Recall is caught loops / all loops.
At 100 × 4, real-loop recall alone is 2 / 5 (40%). The false stops are
`table-blank-nine-columns`, `table-long-identical-rows`, `code-identical-blocks`,
`json-identical-records` and `ten-quoted-copies`. All 25 natural negative cases
pass, but excluding the requested answers would give misleading 100% precision.
Three real emoji cycles, the short-unit loop, the oversized passage and the
approximate cycle are missed.

The best zero-false-stop recall in this sweep is 2 / 12, attained by 384 × 3
and several stricter policies. Relative to 100 × 4, avoiding false stops loses
four caught loops and 33.3 percentage points of recall. No tested policy catches
a majority of loops with zero legitimate stops. **Observe remains the default**
at 100 × 4; Stop remains an expert choice. No saved Observe setting is migrated.
The default makes no stops, so its stop recall is zero and its stop precision
is undefined. This small, deliberately difficult set is a regression corpus,
not an estimate of production prevalence or a measurement of compute saved.

## vLLM comparison

The builder read the pinned
[v0.18.1 scheduler source](https://github.com/vllm-project/vllm/blob/v0.18.1/vllm/v1/core/sched/utils.py)
(blob `c7cb6b94367e7ed331947c7ad27196165054c8ff`) and
[sampling parameters](https://github.com/vllm-project/vllm/blob/v0.18.1/vllm/sampling_params.py).
vLLM compares exact token-ID suffix patterns, from `min_pattern_size` to
`max_pattern_size`, requiring `min_count` consecutive copies. It checks after
each generated token, subject to minimum-token, EOS and length checks. A hit
sets `FINISHED_REPETITION` and `stop_reason = "repetition_detected"`.
Detection is disabled by default. An enabled rule needs a maximum size and
copy count; a minimum size of zero means one token.

Eugene instead normalizes whitespace, compares character passages, checks every
64 normalized characters, rejects primitive units shorter than the configured
minimum, and separates visible text from reasoning, tools and structured output.
vLLM has no such channel distinction in this scheduler rule. It can detect the
short token cycles Eugene deliberately ignores; it can also stop requested
arrays or refrains. It cannot resolve intent from repeated token IDs alone.

The script retains a source-equivalent reference and a faster first-stop search.
Its test compares them exhaustively on binary token sequences of length 0–8,
including disabled parameters. **No vLLM corpus precision or recall is claimed:**
model token IDs/tokenizers were not available, and installation from the sandbox
package index failed. GitHub source access worked. Character or word IDs would
not be a valid numerical replacement for a model tokenizer. No vLLM server ran.

For future token replay, `--tokens tokens.json.gz` accepts a JSON object keyed
by case ID, each value containing `ids` (integer model tokens) and `sha256`
(the case's exact text hash). Document the tokenizer and revision alongside
that artifact. `--verify` checks the optimized search against the source rule
on sampled real prefixes. The token grid has no implied recommended default.

The gateway's `tests/fixtures/repetition-legitimate.jsonl` copies the 44
legitimate texts so its CI can stream each answer verbatim without needing a
sibling specs checkout. The specs regression checks the IDs and hashes stay
in sync.
