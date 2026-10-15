"""Exercise reasoning, stops and cancellation against the real Strata fixture.

Complements actual client runs; it is not itself a claim of harness coverage.
Credentials are read from the workbench's private run.json and never printed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import httpx


def run(root):
    record = json.loads((root / "run.json").read_text(encoding="utf-8"))
    base = record["urls"]["gateway"]
    model = record["model"]
    rows = []
    headers = {"Authorization": "Bearer " + record["applicationKey"]}
    with httpx.Client(timeout=90, trust_env=False, headers=headers) as client:

        def check(label, path, body):
            response = client.post(base + path, json={"model": model, **body})
            response.raise_for_status()
            assert "reasoning" not in response.headers.get(
                "x-eugene-plexus-ignored-settings", ""
            )
            assert "output_config.effort" not in response.headers.get(
                "x-eugene-plexus-ignored-settings", ""
            )
            rows.append(
                {
                    "check": label,
                    "status": response.status_code,
                    "ignored": response.headers.get("x-eugene-plexus-ignored-settings"),
                }
            )
            return response.json()

        for effort in ("none", "low"):
            response = check(
                "Responses effort " + effort,
                "/v1/responses",
                {
                    "input": "Reply with exactly the word READY.",
                    "max_output_tokens": 512,
                    "reasoning": {"effort": effort},
                },
            )
            assert response["status"] == "completed", response["status"]
            text = "".join(
                part.get("text", "")
                for item in response["output"]
                for part in item.get("content", [])
                if part.get("type") == "output_text"
            )
            assert "READY" in text
        for effort, thinking in (
            ("low", {"type": "enabled", "budget_tokens": 1024}),
            ("high", {"type": "disabled"}),
        ):
            response = check(
                "Messages effort " + effort + "/" + thinking["type"],
                "/v1/messages",
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": "Reply with exactly the word READY.",
                        }
                    ],
                    "max_tokens": 512,
                    "output_config": {"effort": effort},
                    "thinking": thinking,
                },
            )
            assert response["stop_reason"] == "end_turn"
            assert "READY" in "".join(
                part.get("text", "") for part in response["content"]
            )
            if thinking["type"] == "disabled":
                assert not any(
                    part["type"] == "thinking" for part in response["content"]
                )

        body = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": "Repeat exactly these three words, separated by spaces: ALPHA STOP OMEGA",
                }
            ],
            "reasoning_effort": "none",
            "temperature": 0,
            "max_tokens": 64,
            "stop": ["STOP"],
        }
        for streaming in (False, True):
            text = ""
            finish = None
            if streaming:
                done = False
                with client.stream(
                    "POST", base + "/v1/chat/completions", json={**body, "stream": True}
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if line == "data: [DONE]":
                            done = True
                        elif line.startswith("data: "):
                            frame = json.loads(line[6:])
                            assert "error" not in frame, frame
                            for choice in frame.get("choices", []):
                                text += choice.get("delta", {}).get("content") or ""
                                finish = choice.get("finish_reason") or finish
                assert done
            else:
                response = client.post(base + "/v1/chat/completions", json=body)
                response.raise_for_status()
                answer = response.json()["choices"][0]
                text, finish = answer["message"]["content"], answer["finish_reason"]
            assert "ALPHA" in text and "STOP" not in text and "OMEGA" not in text, repr(
                text
            )
            assert finish == "stop"
            rows.append(
                {
                    "check": "caller stop, stream=" + str(streaming),
                    "text": text,
                    "finish": finish,
                }
            )

        first = False
        with client.stream(
            "POST",
            base + "/v1/chat/completions",
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": "Count from 1 to 2000, with one number on each line. Do not skip numbers.",
                    }
                ],
                "reasoning_effort": "none",
                "max_tokens": 4096,
                "stream": True,
            },
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    frame = json.loads(line[6:])
                    if any(
                        c.get("delta", {}).get("content")
                        for c in frame.get("choices", [])
                    ):
                        first = True
                        break
        assert first
        deadline = time.perf_counter() + 10
        while time.perf_counter() < deadline:
            status = httpx.get(
                record["strata"] + "/v1/status", timeout=5, trust_env=False
            ).json()
            if status["activity"]["in_flight"] == 0:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("Strata remained busy after cancelling the stream")
        response = check(
            "completion after cancellation",
            "/v1/chat/completions",
            {
                "messages": [
                    {"role": "user", "content": "Reply with exactly the word READY."}
                ],
                "reasoning_effort": "none",
                "max_tokens": 64,
            },
        )
        assert "READY" in response["choices"][0]["message"]["content"]
        rows.append({"check": "cancelled stream releases Strata", "inFlight": 0})
    (root / "protocol-results.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8"
    )
    for row in rows:
        print("PASS", row["check"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbench", type=Path)
    run(parser.parse_args().workbench)
