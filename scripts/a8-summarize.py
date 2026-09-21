"""Summarize retained A8 measurements; never read private credentials/transcripts.

Usage: python scripts/a8-summarize.py RUN_DIRECTORY [--export NEW_DIRECTORY]
An export contains only allowlisted numeric/label records and this summary.
"""

import argparse
import json
import math
from pathlib import Path
import sqlite3


def percentile(values, quantile):
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * quantile) - 1)] if values else None


def summarize(root):
    requests = (
        [
            json.loads(line)
            for line in (root / "requests.jsonl").read_text().splitlines()
        ]
        if (root / "requests.jsonl").exists()
        else json.loads((root / "requests.json").read_text())
    )
    clients = json.loads((root / "clients.json").read_text())
    phases = json.loads((root / "phase-times.json").read_text())
    saturation = json.loads((root / "saturation.json").read_text())
    summary = {"percentileMethod": "nearest-rank", "phases": {}, "targets": {}}
    for phase, timing in phases.items():
        rows = [row for row in requests if row["phase"] == phase]
        good = [
            row
            for row in rows
            if row["status"] == 200 and row["finished"] and not row["streamError"]
        ]
        wall = timing["elapsed"]
        known = [
            row["completionTokens"]
            for row in good
            if row["completionTokens"] is not None
        ]
        events = sorted(
            (instant, change)
            for row in rows
            for instant, change in (
                (row["started"], 1),
                (row["started"] + row["elapsed"], -1),
            )
        )
        outstanding = peak = 0
        for _, change in events:
            outstanding += change
            peak = max(peak, outstanding)
        summary["phases"][phase] = {
            "wallSeconds": wall,
            "requests": len(rows),
            "completed": len(good),
            "peakObservedRequests": peak,
            "rejected": sum(row["status"] != 200 for row in rows),
            "streamErrors": sum(row["streamError"] for row in rows),
            "cancelled": sum(row["cancelled"] for row in rows),
            "knownCompletionTokens": sum(known),
            "completedWithKnownUsage": len(known),
            "knownTokensPerPhaseSecond": sum(known) / wall,
            "ttftP50": percentile(
                [row["ttft"] for row in good if row["ttft"] is not None], 0.5
            ),
            "ttftP95": percentile(
                [row["ttft"] for row in good if row["ttft"] is not None], 0.95
            ),
            "completionP50": percentile([row["elapsed"] for row in good], 0.5),
            "completionP95": percentile([row["elapsed"] for row in good], 0.95),
        }
    for phase, expected, first_limit, complete_limit in (
        ("cold", 1, 60, 120),
        ("single-chat", 12, 30, 60),
        ("mixed", 12, 90, 180),
    ):
        rows = [
            row
            for row in clients
            if row["phase"] == phase and row["client"].startswith("webui")
        ]
        assert len(rows) == expected, (phase, "missing client measurements", len(rows))
        summary["phases"][phase]["chatClients"] = {
            "samples": len(rows),
            "correct": sum(row["correct"] is True for row in rows),
            "ttftP50": percentile(
                [row["ttft"] for row in rows if row["ttft"] is not None], 0.5
            ),
            "ttftP95": percentile(
                [row["ttft"] for row in rows if row["ttft"] is not None], 0.95
            ),
            "completionP50": percentile([row["elapsed"] for row in rows], 0.5),
            "completionP95": percentile([row["elapsed"] for row in rows], 0.95),
        }
        summary["targets"][phase] = all(
            row["status"] == 200
            and row["correct"] is True
            and row["ttft"] is not None
            and row["ttft"] <= first_limit
            and row["elapsed"] <= complete_limit
            for row in rows
        )
    coding = [row for row in clients if row["client"].startswith("claude")]
    assert len(coding) == 3, "Missing real Claude task measurements"
    summary["coding"] = coding
    summary["targets"]["coding"] = all(
        row["elapsed"] <= 600
        and row["exitCode"] == 0
        and not row["isError"]
        and row["checkPassed"]
        and row["checkUnchanged"]
        and row["permissionDenials"] == 0
        and {"Read", "Edit", "Bash"}.issubset(row["tools"])
        for row in coding
    )
    refusal = saturation["refusal"]
    assert summary["phases"]["mixed"]["peakObservedRequests"] == 5, (
        "five clients did not overlap at the gateway"
    )
    assert summary["phases"]["saturation"]["cancelled"] == 3, (
        "missing cancelled-request measurements"
    )
    assert saturation["activeSlotsBeforeCancel"] >= 3, (
        "no evidence of three decoding slots"
    )
    summary["saturation"] = saturation
    summary["targets"]["boundedRefusal"] = (
        refusal["status"] == 429
        and refusal["elapsed"] <= 2
        and bool(refusal["retryAfter"])
    )
    summary["targets"]["cancellation"] = (
        saturation["cancelToIdleSeconds"] <= 10
        and saturation["freshRequest"]["status"] == 200
        and saturation["cancelToFreshFirstContentSeconds"] <= 10
    )
    if (root / "gateway-metrics.json").exists():
        metrics = json.loads((root / "gateway-metrics.json").read_text())
    else:
        connection = sqlite3.connect(
            (root / "metrics.sqlite3").resolve().as_uri() + "?mode=ro", uri=True
        )
        connection.row_factory = sqlite3.Row
        try:
            metrics = [
                dict(row)
                for row in connection.execute(
                    "SELECT r.correlation_id AS requestId, r.client_key_name AS application, "
                    "r.outcome, r.elapsed_ms AS elapsedMs, a.retry_disposition AS retryDisposition, "
                    "a.usage_known AS usageKnown, a.prompt_tokens AS promptTokens, "
                    "a.completion_tokens AS completionTokens FROM request r "
                    "LEFT JOIN attempt a ON a.request_id = r.id ORDER BY r.id, a.seq"
                )
            ]
        finally:
            connection.close()
    cancelled_ids = {row["requestId"] for row in requests if row["cancelled"]}
    cancelled_metrics = [row for row in metrics if row["requestId"] in cancelled_ids]
    assert len(cancelled_metrics) == 3, (
        "cancelled requests missing from retained gateway metrics"
    )
    assert all(
        row["usageKnown"] == 0 and row["retryDisposition"] == "indeterminate"
        for row in cancelled_metrics
    )
    summary["retainedMetrics"] = {
        "attempts": len(metrics),
        "cancelledUsageUnknown": len(cancelled_metrics),
    }
    return summary, requests, clients, phases, saturation, metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--export", type=Path)
    args = parser.parse_args()
    summary, requests, clients, phases, saturation, metrics = summarize(args.directory)
    if (args.directory / "summary.json").exists():
        assert json.loads((args.directory / "summary.json").read_text()) == summary, (
            "retained summary does not match the raw measurements"
        )
    print(json.dumps(summary, indent=2))
    if args.export:
        args.export.mkdir()
        # Only the instrument's public numeric/label schemas, not arbitrary files.
        for name, value in (
            ("summary", summary),
            ("requests", requests),
            ("clients", clients),
            ("phase-times", phases),
            ("saturation", saturation),
            ("gateway-metrics", metrics),
        ):
            (args.export / (name + ".json")).write_text(
                json.dumps(value, indent=2) + "\n", encoding="utf-8"
            )
    raise SystemExit(0 if all(summary["targets"].values()) else 1)
