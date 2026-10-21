"""Evidence integrity and the default-enforcement decision for row 19."""

from __future__ import annotations

import importlib.util
import itertools
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "evaluate_repetition_set", Path(__file__).with_name("evaluate-repetition-set.py")
)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)
CASES = evaluation.load_cases(evaluation.DATA / "cases.jsonl")


@pytest.mark.parametrize("case", [c for c in CASES if "source" in c], ids=lambda c: c["id"])
def test_recorded_text_matches_the_acceptance_artifact(case) -> None:
    source = case["source"]
    record = json.loads(
        (Path(__file__).resolve().parent.parent / source["file"]).read_text(encoding="utf-8")
    )
    for part in source["pointer"].strip("/").split("/"):
        record = record[int(part)] if isinstance(record, list) else record[part]
    assert record == case["_text"]


@pytest.mark.parametrize(
    "case", [c for c in CASES if c["label"] == "legitimate"], ids=lambda c: c["id"]
)
def test_default_preserves_every_legitimate_case(case) -> None:
    assert not evaluation.eugene_run(case, evaluation.Policy())["stop"]


def test_gateway_fixtures_match_all_legitimate_cases() -> None:
    fixture = (
        Path(__file__).resolve().parents[2] / "gateway/tests/fixtures/repetition-legitimate.jsonl"
    )
    if not fixture.exists():
        pytest.skip("Cross-repository check requires the gateway worktree")
    gateway = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines()]
    assert {row["id"]: (row["text"], row["sha256"]) for row in gateway} == {
        case["id"]: (case["_text"], case["sha256"])
        for case in CASES
        if case["label"] == "legitimate"
    }


def test_requested_copies_count_against_the_default_gate() -> None:
    result = evaluation.evaluate(CASES, sweep=True)
    candidate = next(
        row for row in result["eugene"] if (row["min_chars"], row["repeats"]) == (100, 4)
    )
    assert candidate["serving"]["caught"] == 6
    assert candidate["serving"]["loops"] == 12
    assert candidate["serving"]["false_stops_natural"] == 0
    assert candidate["serving"]["false_stops_requested"] == 5
    decision = evaluation.decision(result["eugene"])
    assert decision["recommended_mode"] == "observe"
    assert decision["best_zero_false_stop"]["serving"]["caught"] == 2
    assert evaluation.Policy().mode == decision["recommended_mode"]


def test_vllm_fast_search_matches_source_rule_on_all_small_binary_sequences() -> None:
    # Includes disabled/invalid settings, overlapping cycles and stream prefixes.
    for size in range(9):
        for sequence in itertools.product(range(2), repeat=size):
            ids = list(sequence)
            for rule in ((0, 0, 0), (0, 3, 2), (1, 4, 3), (2, 3, 2), (4, 2, 3), (1, 4, 1)):
                expected = next(
                    (n for n in range(1, size + 1) if evaluation.vllm_check(ids[:n], *rule)),
                    None,
                )
                assert evaluation.vllm_first_stop(ids, *rule) == expected


def test_no_model_tokens_means_no_vllm_precision_claim() -> None:
    assert evaluation.evaluate(CASES[:1], sweep=False)["vllm"] == []
