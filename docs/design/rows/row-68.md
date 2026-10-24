# Row 68: DeepSeek V4.x Flash through Eugene

Lane ENG. Low risk. Source: DI8 in `deepinfer-lessons.md` (the checkpoint
ships no Jinja chat template; tool calls use DeepSeek's DSML format, which
the engine's parser must know; about 110 GB at 3 bits, so a Mac Studio, a
multi-GPU box or a large-RAM box with MoE-aware fit; it drafts five tokens
from its own `nextn` head, which SD1's own-head path covers if the GGUF
keeps it; it needs rented or borrowed hardware). DI-C1 placed it "when
someone asks".

## 1. What it delivers

Everything Eugene's side needs so DeepSeek V4.x Flash runs through it when
the hardware exists: the Library knows the architecture and says what is
missing, a chat template and tool-call parsing are supplied where
upstream lacks them, fit counts it properly, and drafting uses its own
head.

## 2. Design

- **Library:** the V4 architecture in the MLA list (`preflight.py`) and its
  MoE layout in fit (experts in RAM; row 9's cache settings); a model with
  no chat template says so on its page ("This model ships no chat
  template; Eugene supplies DeepSeek V4's") and lists the engines that can
  serve it.
- **Template:** Eugene supplies a reviewed Jinja template for the V4 family
  (from DeepSeek's documented format), applied by the agent with
  llama.cpp's `--chat-template-file` when the GGUF has none; the runtime
  says which template is in effect.
- **Tool calls (DSML):** check llama.cpp's and vLLM's parsers at their
  pinned versions; where one lacks DSML, the gateway parses DSML tool-call
  blocks from the text into tool calls for that model family (the same
  place it handles other model-specific formats), with tests from
  DeepSeek's published examples.
- **Drafting:** the profile's speculation offers the model's own `nextn`
  head (SD1) when the GGUF keeps it, and says so when it does not.

## 3. Repositories

library, agent, gateway, specs (docs; acceptance).

## 4. Tests that fail before

The architecture recognised (a fixture header); "no template" shown and
the supplied template applied in argv; DSML blocks parsed into tool calls
(fixture texts); the own-head drafter offered for a GGUF with `nextn`.

## 5. Acceptance

CI unit and planning tests with fixtures. A real run needs about 110 GB
of memory; the orchestrator runs it if hardware is lent; it is not a
roadmap item otherwise (Troy, 2026-10-21).

## 6. Size and risks

M, about 2 days. Risk: a supplied template that differs from DeepSeek's
own; it cites its source and is replaced when upstream ships one.

**Calls:** none.

## Row 68: DeepSeek V4.x Flash contract staging (2026-10-22)

**Phase 1 only.** The Row 68 design was read from the separate
`calls-1022c/specs/docs/design/rows/row-68.md` worktree. At that phase, this row's specs
worktree did not yet contain that document. No engine, model, or hardware
run was performed for this work.

The existing contracts can describe the GGUF architecture, expert bytes,
embedded-template presence, engine eligibility, and an own-file `nextn`
prediction head. They cannot distinguish an available Eugene template from
the template actually in use. The `chatTemplate` boolean must continue to
mean that the file embeds a template, even when Eugene supplies one. This
requires an additive contract change before consumer code is regenerated:

- Library `GgufDetail.chatTemplateFallback` and
  `CataloguePreflight.chatTemplateFallback` reference `ChatTemplateFallback`.
  The optional, read-only observation names the reviewed template, its
  upstream source, and the engines whose adapters can apply it. Report it
  only after a header confirms a recognized variant and no embedded
  template. An unknown header or a filename is not enough evidence.
- Agent `Runtime.chatTemplate` references `RuntimeChatTemplate`. Its
  read-only observation gives the effective name, source, and SHA-256 of
  the exact template text reported by the engine. An optional id links to
  the Eugene fallback; an optional path names the launch-time file on
  that node. Match against captured launch-time contents before claiming
  an embedded, Eugene, or override source; otherwise report `engine`.
  Omit the observation while unconfirmed or stopped, and clear it before
  another start. Editing a saved setting or template file does not rewrite
  what the existing process is using.
- Neither field changes eligibility or blocks an untested engine. Fallback
  availability does not assert that hardware can load the model. A missing
  effective-template observation does not prevent inference.

The default is an explicit operator override, then the embedded template,
then a reviewed Eugene fallback for the recognized variant on an adapter
that supplies it, then the engine's own behaviour. Phase 2 exposes the
template-file override through the engine's existing GUI flag schema;
`RuntimeSpec.flags` already supports this and needs no new declaration
field. Existing SD1 drafting defaults remain unchanged: offer the own head
only when the tensor table proves it; do not enable MTP based on a name or
on `nextn_predict_layers` alone.

`openapi/run-operations.json` embeds both `GgufDetail` and `Runtime`. It was
not edited by hand. The owner must regenerate that embedded schema through
the normal consumer/export workflow after committing, pushing and pinning
these contracts. Pin and regenerate consumers before implementing Phase 2,
including the model and runtime UI types that will display the observations.

Source inspection found a usable starting point for the remaining fixtures:

- llama.cpp **b11719** already contains a
  [V4 Jinja template](https://github.com/ggml-org/llama.cpp/blob/b11719/models/templates/deepseek-ai-DeepSeek-V4.jinja)
  and [V3.2/V4 DSML format detection](https://github.com/ggml-org/llama.cpp/blob/b11719/common/chat.cpp).
- The agent's reviewed vLLM **v0.29.0** contains the
  [V4 DSML parser](https://github.com/vllm-project/vllm/blob/v0.29.0/vllm/parser/deepseek_v4.py).
  The old `tool_parsers/deepseekv4_tool_parser.py` path is absent at this
  tag; it is not evidence of missing parser support.
- DeepSeek publishes separate
  [V4](https://github.com/deepseek-ai/deepseek-recipe/blob/main/deepseek-recipe-encoding/src/v4/dsv4.rs)
  and [V4.1](https://github.com/deepseek-ai/deepseek-recipe/blob/main/deepseek-recipe-encoding/src/v4/dsv41.rs)
  format implementations. Review and pin the matching source before
  bundling a template or recording DSML samples. Do not assume one template
  covers every V4.x variant.

Phase 2 still owes failing-first GGUF architecture/cache/MoE fit tests,
with-head and stripped-head tests, template selection/override argv tests,
engine read-back and restart tests, model/runtime page coverage, and native
DSML streaming/non-streaming fixture tests. Add a family-scoped gateway
fallback only if those tests show a parser missing in a supported engine;
the source findings above do not establish live behaviour. All of these
checks must use fakes and recorded upstream examples here.

The owner alone runs live acceptance on borrowed/rented hardware with about
110 GB of model memory plus the context and engine overhead. Record the
exact model/quant, engine build, template digest, context, cache/offload and
draft settings. Verify gateway text, streaming/cancellation, tool arguments
and tool-result round trips, effective template reporting, fit versus peak
RAM/VRAM, and own-head drafting on/off with acceptance and timing results.
No model or engine download, engine start, or new performance claim is part
of this contract phase.

## Phase 2 offline implementation (2026-10-22)

The Library adds `deepseek4` to its MLA architecture list. The existing
tensor-table reader already counts the routed `_exps` tensors and keeps
shared experts with the non-expert weights. Tests cover expert offload at
110 GiB, the selected KV precision, and the existing SD1 own-head path
with and without `blk.43.nextn.eh_proj.weight`. A declaration of
`nextn_predict_layers` does not turn a stripped head into a usable head.
For split V4 GGUFs, both consumers inspect all shard tables: the main
blocks can be in the first shard and the retained head in the last. Agent
drafting caches include every shard's stat; later-shard changes or removal
cannot leave an old own-head offer. The Library refreshes old V4 split
scan records, which had only counted the first shard's drafting tensors.
The MLA cache convention is applied only when the header contains both
MLA dimensions; no compression or memory measurement is inferred from a
model name. Current V4 compressed-cache allocations still need comparison
with the estimate on the acceptance machine.

Local scans and remote preflight report `chatTemplateFallback` only from
a complete header with the recognized V4 name and `deepseek4` architecture,
without an embedded template. Cached scans derive it from their saved
header evidence. A catalogue listing or a filename supplies no such fact.
`ModelCapabilities.chatTemplate` continues to describe the file itself.

The agent ships the unmodified llama.cpp b11719 V4 template, upstream blob
`c7819149ae6e73671331c02f03b603cd26d22ef5`, with its source, revision,
digest, review scope and MIT notice beside the asset. The Library currently
lists only `llama_cpp` as able to apply this Eugene fallback. The default
is operator override, embedded template, reviewed V4 fallback, then engine
behaviour. The `chatTemplateFile` override is in the ordinary GUI flag
schema. Explicit CLI and environment overrides retain precedence.
Relative template-file overrides are captured from the engine's launch
directory, the same directory the engine uses to open them.

V4.1 and Flash-0731 do not silently receive the V4 template: their formats
differ, and a separate fallback has not been reviewed for them. They are
still allowed to launch with an embedded or operator-supplied template,
or the engine's own support. There is no new eligibility gate.

The launch planner captures the selected template's exact bytes. llama.cpp's
health probe reads `/props` once for both capabilities and template text.
Only that engine-confirmed text creates `Runtime.chatTemplate`; its source
is attributed only on an exact match to the launch capture. A mismatch is
`engine` with no fallback id or file path. A later file or profile edit
does not rewrite the running observation. Stop, manual restart and automatic
restart cannot reuse a previous process's confirmation. Missing `/props`
information does not prevent a ready runtime from serving.

Source review found native incremental and complete V4 DSML support in
llama.cpp b11719 (`common/chat.cpp`, `common/parsers/deepseek.cpp`) and
vLLM v0.29.0 (`vllm/parser/deepseek_v4.py`). No Eugene parser is added for
these engines. The published vLLM DSML example is a recorded fixture;
offline rendering tests cover its string and JSON arguments and tool-result
turns. These are source review and prompt tests, not a claim that a native
engine or hardware tool round trip was run here.

`run-operations.json` was exported from the Library's actual FastAPI router,
using the same app construction as `scripts/run-operations-checks.py`,
with document metadata preserved. `scripts/vendor-platform.py --repo library`
and `--repo agent` regenerated the consumer copies and integrity manifests.
The phase-1 YAML contracts, `SPECS_REF` pins and generated model code remain
unchanged.

The model-page sentence and runtime display still require a UI worktree
pinned and regenerated to contract `3564734`. This workspace provides only
specs, agent and library; the existing main UI's generated types do not
contain the new observations. No main checkout or UI generated code was
edited. Live acceptance remains the hardware run described above.

### Offline validation

Both `tests/test_deepseek_flash.py` files were written and run red before
implementation: MLA accounting and fit, local/preflight fallback evidence,
template selection/capture, GUI override, engine read-back and prompt
fixtures. Separate red regressions caught stale automatic-restart
confirmation, a head in a later shard, and relative override resolution.
Existing own-head and stripped-head SD1 behaviour was also exercised.

Final targeted agent checks: **105 passed**. Final whole Library suite:
**1117 passed, 30 skipped**. Final whole agent suite: **2927 passed,
20 skipped, 1 failed**. The failure is the existing real app-install test:
uv's managed Python download is denied by the sandbox network policy
(Windows socket error 10013), before it can test the missing `__main__`.
The 8080-listener test is explicitly skipped for this task's port rule;
the temporary pytest policy names `specs#95` and changes no repository test.
An earlier agent run also hit Windows `os.replace` access denied (error 5)
in the `test_ui_proxy` config fixture. It did not recur in the final run;
no unrelated config-write fix is claimed.

Specs `python -m pytest -q scripts`: **372 passed, 3 skipped**, with the
cached phase-1 gateway source on `PYTHONPATH` for the repetition-evaluation
test's import. The initial attempt without that source stopped at collection.
No specs Python script was changed. Both packages passed `ruff check src
tests`, `ruff format --check src tests`, and both `mypy --platform linux src`
and `mypy src`. Vendored-integrity, specs-ref stamps, matching protocol
copies and `git diff --check` passed. The final whole suites followed the
split-head and relative-override fixes; no model, engine build or real
engine was downloaded or started. Test files and exports used temporary
storage under the worktree root's `.codex-tmp/`. The exact resolved cleanup
target was verified, but both the combined cleanup command and a separate
literal-path recursive deletion were rejected as "blocked by policy".
Approvals are disabled; `.codex-tmp/` remains for owner cleanup.

No commit or push was made. GitHub assignment/label updates were rejected
because the connector requires approval and this workspace's approval
policy is `never`; the issue was not marked green.
