"""Sabotage pass: reasoning through both doors, and the local samplers.

2026-09-23. Restores from a COPY, never `git checkout --`, and opens with
a baseline on both gates (feedback memory: a restore that reverts
uncommitted work deletes the change under test, and every later result
reads *caught* for the wrong reason).

Two repos, because the fix is two repos: the driver has to read
`reasoning_content`/`reasoning` off the backend and put the samplers on
the wire; the gateway has to carry both to and from each door in that
door's own vocabulary.

Three kinds of sabotage, as in r34-sabotage.py: put the finding back,
put the over-correction in, and take the discriminator apart. The
over-corrections this change invites are specific:

* read one engine's field name and not the other's;
* accept a null `content` always, not only beside reasoning or calls;
* send reasoning to OpenAI's own endpoint, which refuses it;
* fill in a `parallel_tool_calls` default the caller never chose;
* treat `top_k: 0` or `parallel_tool_calls: false` as unset;
* show reasoning to an Anthropic client that never enabled thinking,
  or show its text under `display: "omitted"`;
* trust a signature that is not ours;
* report cached input ON TOP of an unreduced `input_tokens`.

An escape means the check set cannot tell the fix from its opposite.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")

GATEWAY = "gateway"
INFERENCE = "src/eugene_plexus_gateway/routes/inference.py"
ANTHROPIC = "src/eugene_plexus_gateway/anthropic.py"
DRIVER_CLIENT = "src/eugene_plexus_gateway/driver_client.py"
CHAT_CONTRACT = "src/eugene_plexus_gateway/chat_contract.py"

DRIVER = "inference-driver"
OPENAI_HTTP = "src/eugene_plexus_inference_driver/engines/openai_compat_http.py"
BASE = "src/eugene_plexus_inference_driver/engines/base.py"
ROUTE = "src/eugene_plexus_inference_driver/routes/generate.py"

FILES = {
    GATEWAY: (INFERENCE, ANTHROPIC, DRIVER_CLIENT, CHAT_CONTRACT),
    DRIVER: (OPENAI_HTTP, BASE, ROUTE),
}

GATES = {
    GATEWAY: (
        "tests/test_reasoning_and_local_samplers.py",
        "tests/test_anthropic_messages.py",
        "tests/test_chat_contract.py",
        "tests/test_inference.py",
        "tests/test_tool_calling.py",
        "tests/test_failover.py",
        "tests/test_request_path_contract.py",
        "tests/test_stream_bookkeeping.py",
        "tests/test_client_disconnect.py",
    ),
    DRIVER: (
        "tests/test_reasoning_and_local_samplers.py",
        "tests/test_sampling_and_filter.py",
        "tests/test_tool_calling.py",
        "tests/test_openai_api_adapter.py",
        "tests/test_adapters.py",
        "tests/test_generate_route.py",
        "tests/test_caller_settings.py",
        "tests/test_thinking_filter.py",
    ),
}

UNIT_TIMEOUT = 900


def run_gate(repo: str) -> tuple[int, str]:
    py = ROOT / repo / ".venv" / "Scripts" / "python.exe"
    try:
        done = subprocess.run(
            [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", *GATES[repo]],
            cwd=ROOT / repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=UNIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:]


# (label, repo, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # ----------------------------------------------------------------- #
    # driver: reading the reasoning
    # ----------------------------------------------------------------- #
    (
        "THE FINDING: the batch result carries no reasoning",
        DRIVER,
        OPENAI_HTTP,
        'reasoning=reasoning if self._thinking_mode != "off" else None,',
        "reasoning=None,",
    ),
    (
        "THE FINDING, streamed: reasoning deltas are read past",
        DRIVER,
        OPENAI_HTTP,
        "                            yield Chunk(reasoning=thought)\n",
        "                            pass\n",
    ),
    (
        "only llama.cpp's field name is read (vLLM's thinking lost)",
        DRIVER,
        OPENAI_HTTP,
        'for key in ("reasoning_content", "reasoning"):',
        'for key in ("reasoning_content",):',
    ),
    (
        "only vLLM's field name is read (llama.cpp's thinking lost)",
        DRIVER,
        OPENAI_HTTP,
        'for key in ("reasoning_content", "reasoning"):',
        'for key in ("reasoning",):',
    ),
    (
        "a vLLM reasoning-only turn still raises (a 502 for a good reply)",
        DRIVER,
        OPENAI_HTTP,
        "if not tool_calls and not reasoning:",
        "if not tool_calls:",
    ),
    (
        "OVER-CORRECTION: a null content is accepted with nothing beside it",
        DRIVER,
        OPENAI_HTTP,
        "if not tool_calls and not reasoning:",
        "if False:",
    ),
    (
        "thinkingMode off still returns reasoning on the batch path",
        DRIVER,
        OPENAI_HTTP,
        'reasoning=reasoning if self._thinking_mode != "off" else None,',
        "reasoning=reasoning,",
    ),
    (
        "thinkingMode off still streams reasoning",
        DRIVER,
        OPENAI_HTTP,
        'show_reasoning = self._thinking_mode != "off"',
        "show_reasoning = True",
    ),
    (
        "the stream's terminal result drops the reasoning it forwarded",
        DRIVER,
        OPENAI_HTTP,
        'reasoning="".join(reasoned) or None,',
        "reasoning=None,",
    ),
    (
        "the route frames a reasoning token as text (thinking spliced into the answer)",
        DRIVER,
        ROUTE,
        "return f\"event: token\\ndata: {json.dumps({'reasoning': reasoning})}\\n\\n\"",
        "return f\"event: token\\ndata: {json.dumps({'text': reasoning})}\\n\\n\"",
    ),
    # ----------------------------------------------------------------- #
    # driver: reasoning handed back
    # ----------------------------------------------------------------- #
    (
        "a history turn's reasoning is never sent back up",
        DRIVER,
        OPENAI_HTTP,
        "if send_reasoning and reasoning:",
        "if False:",
    ),
    (
        "OVER-CORRECTION: reasoning is sent to OpenAI's own endpoint too",
        DRIVER,
        OPENAI_HTTP,
        "send_reasoning=not _is_openai_endpoint(self._base_url)",
        "send_reasoning=True",
    ),
    (
        "sent under vLLM's name, which llama.cpp ignores (measured)",
        DRIVER,
        OPENAI_HTTP,
        'msg["reasoning_content"] = reasoning',
        'msg["reasoning"] = reasoning',
    ),
    # ----------------------------------------------------------------- #
    # driver: the samplers
    # ----------------------------------------------------------------- #
    (
        "THE FINDING one layer down: the samplers never reach the wire",
        DRIVER,
        OPENAI_HTTP,
        "            payload[key] = value\n",
        "            pass\n",
    ),
    (
        "a truthiness guard drops top_k=0 and parallel_tool_calls=false",
        DRIVER,
        OPENAI_HTTP,
        "            if value is None:\n                continue\n            if field in unsupported:",
        "            if not value:\n                continue\n            if field in unsupported:",
    ),
    (
        "OpenAI's own endpoint is sent top_k (its 'Unrecognized argument' 400)",
        DRIVER,
        OPENAI_HTTP,
        "            unsupported |= _LOCAL_ENGINE_SETTINGS\n",
        "            pass\n",
    ),
    (
        "OVER-CORRECTION: OpenAI's endpoint refuses the penalties too",
        DRIVER,
        OPENAI_HTTP,
        '_LOCAL_ENGINE_SETTINGS = frozenset({"topK", "minP"})',
        '_LOCAL_ENGINE_SETTINGS = frozenset({"topK", "minP", "frequencyPenalty"})',
    ),
    (
        "a fixed-sampler model is sent the penalties",
        DRIVER,
        OPENAI_HTTP,
        '{"temperature", "topP", "frequencyPenalty", "presencePenalty"}',
        '{"temperature", "topP"}',
    ),
    (
        "a local backend does not advertise top_k (the gateway routes around it)",
        DRIVER,
        OPENAI_HTTP,
        '            "responseFormat",\n            "topK",\n',
        '            "responseFormat",\n',
    ),
    (
        "the agentic CLIs drop an explicit sampler instead of refusing it",
        DRIVER,
        BASE,
        '            "topK",\n            "minP",\n            "frequencyPenalty",\n'
        '            "presencePenalty",\n            "parallelToolCalls",\n        },',
        "        },",
    ),
    # ----------------------------------------------------------------- #
    # driver: stop sequence and usage
    # ----------------------------------------------------------------- #
    (
        "OVER-CORRECTION: any stop_reason string is named a stop sequence",
        DRIVER,
        OPENAI_HTTP,
        "if isinstance(reason, str) and request.stop and reason in request.stop:",
        "if isinstance(reason, str):",
    ),
    (
        "vLLM's stop_reason is never read on the batch path",
        DRIVER,
        OPENAI_HTTP,
        "        stop_sequence = _stop_sequence(first, request)\n",
        "        stop_sequence = None\n",
    ),
    (
        "vLLM's stop_reason is never read on the streamed path",
        DRIVER,
        OPENAI_HTTP,
        "                            stop_sequence = _stop_sequence(choice, request)\n",
        "                            stop_sequence = None\n",
    ),
    (
        "cached prompt tokens are never read",
        DRIVER,
        OPENAI_HTTP,
        'cachedPromptTokens=_detail(usage, "prompt_tokens_details", "cached_tokens"),',
        "cachedPromptTokens=None,",
    ),
    (
        "OVER-CORRECTION: an unreported reasoning count becomes zero",
        DRIVER,
        OPENAI_HTTP,
        'reasoningTokens=_detail(usage, "completion_tokens_details", "reasoning_tokens"),',
        'reasoningTokens=_detail(usage, "completion_tokens_details", "reasoning_tokens") or 0,',
    ),
    # ----------------------------------------------------------------- #
    # gateway: OpenAI door, request side
    # ----------------------------------------------------------------- #
    (
        "THE FINDING: top_k accepted and put nowhere",
        GATEWAY,
        INFERENCE,
        "        topK=body.top_k,\n",
        "",
    ),
    (
        "top_k carried but not claimed as the caller's (routed onto a backend that drops it)",
        GATEWAY,
        INFERENCE,
        '                ("top_k", "topK"),\n',
        "",
    ),
    (
        "OVER-CORRECTION: a parallel_tool_calls default is invented",
        GATEWAY,
        INFERENCE,
        "        parallelToolCalls=body.parallel_tool_calls,\n",
        "        parallelToolCalls=True if body.parallel_tool_calls is None"
        " else body.parallel_tool_calls,\n",
    ),
    (
        "developer is passed through as a role no backend has",
        GATEWAY,
        INFERENCE,
        'role = "system" if message.role.value == "developer" else message.role.value',
        "role = message.role.value",
    ),
    (
        "an assistant turn's reasoning_content is not handed to the driver",
        GATEWAY,
        INFERENCE,
        "        reasoning=message.reasoning_content,\n",
        "        reasoning=None,\n",
    ),
    (
        "reasoning_content on a user message is silently dropped, not refused",
        GATEWAY,
        CHAT_CONTRACT,
        'if message.reasoning_content is not None and message.role.value != "assistant":',
        "if False:",
    ),
    # ----------------------------------------------------------------- #
    # gateway: OpenAI door, response side
    # ----------------------------------------------------------------- #
    (
        "THE FINDING at the door: the batch message carries no reasoning",
        GATEWAY,
        INFERENCE,
        "                    reasoning_content=response.reasoning,\n",
        "",
    ),
    (
        "every reply grows a null reasoning_content",
        GATEWAY,
        INFERENCE,
        '        if message.get("reasoning_content") is None:\n'
        '            message.pop("reasoning_content", None)\n',
        "",
    ),
    (
        "streamed reasoning is sent as content (thinking spliced into the answer)",
        GATEWAY,
        INFERENCE,
        "delta=Delta(reasoning_content=event.reasoning),",
        "delta=Delta(content=event.reasoning),",
    ),
    (
        "the real driver client reads past a reasoning token",
        GATEWAY,
        DRIVER_CLIENT,
        "                    yield StreamEvent(reasoning=reasoning)\n",
        "                    pass\n",
    ),
    (
        "reasoning is not a commit point (another model spliced after the thinking)",
        GATEWAY,
        DRIVER_CLIENT,
        "                        committed = True\n",
        '                        committed = committed or not getattr(event, "reasoning", "")\n',
    ),
    (
        "cached prompt tokens never reach the OpenAI usage",
        GATEWAY,
        INFERENCE,
        "        prompt_tokens_details=PromptTokensDetails(cached_tokens=cached)\n",
        "        prompt_tokens_details=None\n",
    ),
    (
        "OVER-CORRECTION: an unreported reasoning count appears anyway",
        GATEWAY,
        INFERENCE,
        "        if reasoning is not None\n",
        "        if True\n",
    ),
    # ----------------------------------------------------------------- #
    # gateway: Anthropic door
    # ----------------------------------------------------------------- #
    (
        "THE FINDING: top_k accepted on the Anthropic door and put nowhere",
        GATEWAY,
        ANTHROPIC,
        "        top_k=body.top_k,\n",
        "",
    ),
    (
        "top_k refused again, as before today",
        GATEWAY,
        ANTHROPIC,
        '_REFUSED_TOP_LEVEL = ("mcp_servers",)',
        '_REFUSED_TOP_LEVEL = ("mcp_servers", "top_k")',
    ),
    (
        "THE FINDING: disable_parallel_tool_use silently dropped",
        GATEWAY,
        ANTHROPIC,
        "        parallel_tool_calls=_parallel_tool_calls(body.tool_choice),\n",
        "",
    ),
    (
        "disable_parallel_tool_use carried without inverting its sense",
        GATEWAY,
        ANTHROPIC,
        "return None if disable is None else not disable",
        "return None if disable is None else disable",
    ),
    (
        "OVER-CORRECTION: parallel tool calls filled in when the caller said nothing",
        GATEWAY,
        ANTHROPIC,
        "return None if disable is None else not disable",
        "return True if disable is None else not disable",
    ),
    (
        "thinking blocks shown to a client that never enabled thinking",
        GATEWAY,
        ANTHROPIC,
        '    if not isinstance(thinking, Mapping) or thinking.get("type") == "disabled":\n'
        "        return None\n",
        '    if not isinstance(thinking, Mapping) or thinking.get("type") == "disabled":\n'
        '        return "text"\n',
    ),
    (
        "display omitted ignored: the text is shown anyway",
        GATEWAY,
        ANTHROPIC,
        'return "omitted" if thinking.get("display") == "omitted" else "text"',
        'return "text"',
    ),
    (
        "OVER-CORRECTION: omitted drops the block, and continuity with it",
        GATEWAY,
        ANTHROPIC,
        "    if reasoning and display is not None:\n",
        '    if reasoning and display == "text":\n',
    ),
    (
        "an omitted block's signature carries nothing",
        GATEWAY,
        ANTHROPIC,
        'return {"type": "thinking", "thinking": "", "signature": encode_signature(reasoning)}',
        'return {"type": "thinking", "thinking": "", "signature": ""}',
    ),
    (
        "a returned signature is never decoded (tool loop loses its reasoning)",
        GATEWAY,
        ANTHROPIC,
        'thought = _field(block, "thinking") or decode_signature(_field(block, "signature"))',
        'thought = _field(block, "thinking") or None',
    ),
    (
        "a signature that is not ours is trusted",
        GATEWAY,
        ANTHROPIC,
        "if not isinstance(signature, str) or not signature.startswith(_SIGNATURE_PREFIX):",
        "if not isinstance(signature, str):",
    ),
    (
        "a corrupt signature is leniently decoded",
        GATEWAY,
        ANTHROPIC,
        "signature[len(_SIGNATURE_PREFIX) :], validate=True",
        "signature[len(_SIGNATURE_PREFIX) :]",
    ),
    (
        "the thinking block is left open when the text block opens",
        GATEWAY,
        ANTHROPIC,
        "        out: list[str] = self._close_thinking()\n",
        "        out: list[str] = []\n",
    ),
    (
        "an omitted stream leaks the thinking text as deltas",
        GATEWAY,
        ANTHROPIC,
        '        if self._display == "omitted":\n'
        "            self._withheld.append(chunk)\n"
        "            return out\n",
        "",
    ),
    (
        "an omitted stream never sends its signature",
        GATEWAY,
        ANTHROPIC,
        'if self._display == "omitted" and self._withheld:',
        "if False:",
    ),
    (
        "hidden reasoning opens a block anyway",
        GATEWAY,
        ANTHROPIC,
        "        if self._display is None:\n            return []\n",
        "",
    ),
    (
        "streamed reasoning never reaches the translator",
        GATEWAY,
        INFERENCE,
        "                    for chunk in translator.thinking(event.reasoning):\n",
        "                    for chunk in []:\n",
    ),
    (
        "cached input is not split out",
        GATEWAY,
        ANTHROPIC,
        '    cached = getattr(usage, "cachedPromptTokens", None) or 0\n',
        "    cached = 0\n",
    ),
    (
        "OVER-CORRECTION: cached input counted twice (input_tokens not reduced)",
        GATEWAY,
        ANTHROPIC,
        '        "input_tokens": prompt - cached,\n',
        '        "input_tokens": prompt,\n',
    ),
    (
        "the matched stop sequence is not echoed (batch)",
        GATEWAY,
        ANTHROPIC,
        '"stop_sequence": stop_sequence if stop_reason(finish) == "stop_sequence" else None,',
        '"stop_sequence": None,',
    ),
    (
        "the matched stop sequence is not echoed (stream)",
        GATEWAY,
        ANTHROPIC,
        '"stop_sequence": stop_sequence if reason == "stop_sequence" else None,',
        '"stop_sequence": None,',
    ),
    (
        "honoured thinking still named on the ignored-settings header",
        GATEWAY,
        ANTHROPIC,
        '            value.get("budget_tokens") is not None or value.get("type") == "disabled"\n',
        "            True\n",
    ),
    (
        "THE LIVE FINDING: output_config refused, so Claude Code fails every request",
        GATEWAY,
        ANTHROPIC,
        "        if name not in AnthropicMessagesRequest.model_fields and name not in (",
        '        if name == "output_config" or name not in AnthropicMessagesRequest.model_fields'
        " and name not in (",
    ),
    (
        "OVER-CORRECTION: any output_config key accepted, structured output silently dropped",
        GATEWAY,
        ANTHROPIC,
        '_ACCEPTED_OUTPUT_CONFIG = frozenset({"effort"})',
        '_ACCEPTED_OUTPUT_CONFIG = frozenset({"effort", "format", "task_budget"})',
    ),
    (
        "output_config accepted but not disclosed as unenforced",
        GATEWAY,
        ANTHROPIC,
        '        if name != "thinking":\n            return True\n',
        '        if name != "thinking":\n            return name != "output_config"\n',
    ),
    (
        "OVER-CORRECTION: an unenforced budget is no longer disclosed",
        GATEWAY,
        ANTHROPIC,
        '            value.get("budget_tokens") is not None or value.get("type") == "disabled"\n',
        "            False\n",
    ),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    backup = Path(tempfile.mkdtemp(prefix="reasoning-sabotage-"))
    for repo, relatives in FILES.items():
        for relative in relatives:
            destination = backup / repo / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / repo / relative, destination)
    print(f"copy in {backup}\n")

    for repo in FILES:
        code, out = run_gate(repo)
        print(f"[baseline] {repo}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    print()

    # Optional label filter: `python ... "never decoded"` re-runs only the
    # sabotages whose label contains that text (a fixed anchor, say).
    wanted = [s for s in SABOTAGES if not sys.argv[1:] or any(a in s[0] for a in sys.argv[1:])]
    caught = escaped = 0
    for label, repo, relative, old, new in wanted:
        path = ROOT / repo / relative
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {repo}: {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run_gate(repo)
        finally:
            shutil.copy2(backup / repo / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {repo}: {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {repo}: {label}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(wanted)} sabotages")
    ok = True
    for repo in FILES:
        code, out = run_gate(repo)
        print(f"[restored] {repo}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            ok = False
    if not ok:
        return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
