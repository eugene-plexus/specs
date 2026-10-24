"""Check the acceptance fixture without starting any service."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def acceptance():
    path = Path(__file__).with_name("row57-responses-tools-acceptance.py")
    spec = importlib.util.spec_from_file_location("row57_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["write", "local_shell", "shell", "apply_patch"])
def test_fixture_calls_each_adapter_and_checks_its_result(name):
    module = acceptance()
    body = {
        "messages": [{"role": "user", "content": "go"}],
        "tools": [{"type": "function", "function": {"name": name}}],
    }
    text, calls = module.answer(body)
    assert text is None
    assert calls[0]["function"]["name"] == name
    assert json.loads(calls[0]["function"]["arguments"]) == module.ARGUMENTS[name]
    body["messages"] += [
        {"role": "assistant", "tool_calls": calls},
        {
            "role": "tool",
            "tool_call_id": calls[0]["id"],
            "content": "ROW57-TOOL-RESULT",
        },
    ]
    assert module.answer(body) == (module.FINAL, None)


def test_fixture_compaction_checks_the_summary_budget():
    module = acceptance()
    body = {
        "messages": [{"role": "developer", "content": "Write at most 4,000 tokens."}],
        "max_tokens": 4000,
    }
    assert module.answer(body) == (module.SUMMARY, None)
    with pytest.raises(AssertionError):
        module.answer({**body, "max_tokens": 5000})


def test_fixture_observes_expanded_summary_as_instruction():
    module = acceptance()
    assert module.answer(
        {
            "messages": [
                {"role": "system", "content": module.SUMMARY},
                {"role": "user", "content": "continue"},
            ]
        }
    ) == (module.EXPANDED, None)
