"""Terminal client for the node's measurement job; capture replay for live acceptance.

Use an operator credential JSON file holding `token`, never a token in shell history.
Replay JSON: {"sessions": [{"turns": [{"messages": [...], "max_tokens": 317,
"pauseSeconds": 2}]}]}. Replay sends those messages only through the gateway,
uses a temporary local-only key and prints observations, never captured content.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path

import httpx

BASE = "/v1/serving-measurements"


def sentence(job):
    knee = job.get("knee")
    if not knee:
        return "No usable level measured yet."
    speed, people = round(knee["tokensPerSecondEach"]), knee["people"]
    if not knee["found"]:
        return f"At least {people} people at {speed} tok/s each. The limit is above {people}."
    if people == 1:
        return f"One person at {speed} tok/s. A second person slows both."
    workload = {"agents": "agent sessions", "chat": "chat sessions", "streams": "streams"}[
        job["request"]["workload"]
    ]
    return (
        f"{people} people at {speed} tok/s each, first token in "
        f"{knee['ttftP50Ms'] / 1000:.1f} s ({workload})."
    )


async def replay(args, credential):
    from eugene_plexus_agent._http import internal_client
    from eugene_plexus_agent.serving_sweep import Sweep, knee_for, people_levels

    sessions = json.loads(args.replay.read_text(encoding="utf-8"))["sessions"]
    if not sessions or any(not s.get("turns") for s in sessions):
        raise ValueError("Each captured session must contain turns.")
    for session in sessions:
        for turn in session["turns"]:
            if not isinstance(turn.get("messages"), list) or not turn["messages"]:
                raise ValueError("Each captured turn must contain messages.")

    class CapturedSession:
        def __init__(self, turn, identity):
            self.messages, self.identity = turn["messages"], identity
            self.reuse = None
            self.workload = "streams"
            self.limit = turn.get("max_tokens", 317)

        def output_limit(self):
            return self.limit

    class Replay(Sweep):
        async def turn(self, session, *, counted=True):
            state = self.positions.setdefault(
                session.identity, [self.rng.randrange(len(sessions)), 0]
            )
            turns = sessions[state[0]]["turns"]
            turn = turns[state[1] % len(turns)]
            result = await super().turn(CapturedSession(turn, session.identity), counted=counted)
            state[1] += 1
            pause = min(
                max(0, turn.get("pauseSeconds", 0)), max(0, self.until - time.perf_counter())
            )
            await asyncio.sleep(pause)
            return result

        async def level(self, people, seconds, workload, progress=None):
            self.positions = {}
            self.until = time.perf_counter() + seconds
            return await super().level(people, seconds, "streams", progress)

    url = args.agent.rstrip("/")
    headers = {"Authorization": "Bearer " + credential}
    async with internal_client(timeout=httpx.Timeout(120, connect=5)) as client:
        response = await client.get(url + "/v1/runtimes", headers=headers)
        response.raise_for_status()
        runtime = next(r for r in response.json()["runtimes"] if r["name"] == args.runtime)
        if runtime["status"] != "ready":
            raise ValueError(f"{args.runtime} is {runtime['status']}. Start it before replay.")
        check = await client.post(
            url + BASE + "/preflight", headers=headers, json={"runtime": args.runtime}
        )
        check.raise_for_status()
        if check.json()["problems"] or check.json()["otherReplicas"]:
            raise ValueError(f"Replay needs one ready copy: {check.json()}")
        model = runtime["modelAlias"]
        if "*" in model:
            raise ValueError(
                "An alias with a wildcard cannot scope a measurement key to one model."
            )
        created = await client.post(
            url + "/v1/auth/client-keys",
            headers=headers,
            json={
                "name": "Measurement replay",
                "ttlDays": 1,
                "limits": {
                    "localOnly": True,
                    "allowedModels": [model],
                    "maxConcurrentRequests": 64,
                    "requestsPerMinute": 10000,
                },
            },
        )
        created.raise_for_status()
        key = created.json()
        levels = []
        try:
            sweep = Replay(
                client,
                url + "/api/proxy/gateway",
                key["token"],
                args.runtime,
                runtime.get("node") or "this node",
                model,
                (runtime.get("capabilities") or {}).get("contextLength") or 32768,
                random.Random(args.seed),
            )
            knee = None
            maximum = args.max_people or min(
                256, 4 * ((runtime.get("capabilities") or {}).get("parallelSlots") or 1)
            )
            window = 3600 if args.full else args.window_seconds or 300
            for people in people_levels(maximum):
                levels.append(await sweep.level(people, window, "streams"))
                knee = knee_for(levels, args.ttft_threshold_ms, args.speed_ratio_threshold)
                if knee and knee.found:
                    break
            return {
                "replay": args.replay.name,
                "runtime": args.runtime,
                "request": {"workload": "agents"},
                "levels": [level.model_dump(mode="json") for level in levels],
                "knee": knee.model_dump(mode="json") if knee else None,
            }
        finally:
            revoked = await client.delete(
                url + "/v1/auth/client-keys/" + key["key"]["id"], headers=headers
            )
            revoked.raise_for_status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--workload", choices=("agents", "chat", "streams"), default="agents")
    parser.add_argument("--max-people", type=int)
    parser.add_argument("--window-seconds", type=int)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--ttft-threshold-ms", type=float, default=1000)
    parser.add_argument("--speed-ratio-threshold", type=float, default=2 / 3)
    parser.add_argument(
        "--stop-replicas",
        action="store_true",
        help="Consent to stopping the replicas named by preflight; they start again after",
    )
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    credential = json.loads(args.credential_file.read_text(encoding="utf-8"))["token"]
    if args.replay:
        job = asyncio.run(replay(args, credential))
    else:
        with httpx.Client(
            base_url=args.agent.rstrip("/"),
            headers={"Authorization": "Bearer " + credential},
            trust_env=False,
            timeout=20,
        ) as client:
            body = {
                "runtime": args.runtime,
                "workload": args.workload,
                "full": args.full,
                "seed": args.seed,
                "ttftThresholdMs": args.ttft_threshold_ms,
                "speedRatioThreshold": args.speed_ratio_threshold,
            }
            for name, value in (
                ("maxPeople", args.max_people),
                ("windowSeconds", args.window_seconds),
            ):
                if value is not None:
                    body[name] = value
            check = client.post(BASE + "/preflight", json=body)
            check.raise_for_status()
            print(json.dumps(check.json()), file=sys.stderr)
            if args.stop_replicas:
                body["stopReplicas"] = check.json()["otherReplicas"]
            response = client.post(BASE, json=body)
            response.raise_for_status()
            job = response.json()
            try:
                while job["state"] == "running":
                    time.sleep(1)
                    response = client.get(BASE)
                    response.raise_for_status()
                    job = next(j for j in response.json()["measurements"] if j["id"] == job["id"])
            finally:
                if job["state"] == "running" or job["keyLive"]:
                    response = client.post(BASE + "/" + job["id"] + "/cancel")
                    response.raise_for_status()
                    job = response.json()
    print(sentence(job), file=sys.stderr)
    print(json.dumps(job, indent=2))
    return 0 if job.get("state", "completed") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
