"""The acceptance must count every answer and preserve an honest off observation."""

import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest


def acceptance():
    spec = importlib.util.spec_from_file_location(
        "di7", Path(__file__).with_name("di7-same-answer-acceptance.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_di7_checks_ten_byte_identical_answers_and_records_off_without_a_difference():
    di7 = acceptance()
    for enabled in (True, False):
        result = di7.answer_record(["same\r\n"] * 10)
        di7.check_answers(enabled, result)
        assert result["uniqueAnswers"] == 1
        assert result["answers"] == ["same\r\n"] * 10
    changed = di7.answer_record(["same"] * 9 + ["different"])
    di7.check_answers(False, changed)
    with pytest.raises(AssertionError, match="2 distinct answers"):
        di7.check_answers(True, changed)
    with pytest.raises(AssertionError, match="10 answers"):
        di7.check_answers(True, di7.answer_record(["same"] * 9))


def test_di7_byte_comparison_does_not_normalize_or_drop_empty_answers():
    di7 = acceptance()
    result = di7.answer_record(["a\n"] * 9 + ["a\r\n"])
    assert result["uniqueAnswers"] == 2
    with pytest.raises(AssertionError, match="empty"):
        di7.check_answers(True, di7.answer_record([""] * 10))


def test_di7_sends_fixed_prompt_only_after_three_background_requests_are_admitted():
    di7 = acceptance()

    async def exercise():
        admitted = asyncio.Event()
        release = asyncio.Event()
        others = []

        async def handle(request):
            if request.url.path == "/metrics":
                await admitted.wait()
                return httpx.Response(
                    200,
                    text=(
                        "llamacpp:requests_processing 1\nllamacpp:requests_deferred 2\n"
                    ),
                )
            body = json.loads(request.content)
            assert body["cache_prompt"] is False
            if body["prompt"] == di7.PROMPT:
                assert len(others) == 3
                assert body["seed"] == di7.SEED
                release.set()
                return httpx.Response(200, json={"content": "the exact answer\r\n"})
            others.append(body)
            if len(others) == 3:
                admitted.set()
            await release.wait()
            return httpx.Response(200, json={"content": "background"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            answer, busy = await di7.under_load(client, "http://engine.invalid", 0)
        assert answer == "the exact answer\r\n"
        assert busy == 3
        assert len({body["prompt"] for body in others}) == 3

    asyncio.run(exercise())
