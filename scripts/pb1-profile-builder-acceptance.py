"""PB1 acceptance: a real agent builds a profile with the real llama.cpp tools.

docs/design/profile-builder.md is the design; this drives it end to end over
HTTP against a disposable agent (its own port, its own folder, every ambient
EUGENE_PLEXUS_* variable dropped), so the live install is never touched.

    python pb1-profile-builder-acceptance.py --server DIR/llama-server(.exe) \
        --model FILE.gguf [--busy-model FILE.gguf] [--accuracy medium] \
        [--margin MIB] [--cpu] [--expect-moe] [--report out.json]

--busy-model declares and starts a real runtime first, so the ask-stop-
restart path is exercised with a real process: refused without agreement,
stopped with it (reason `measurement`), started again afterwards.
--margin simulates a smaller card through llama.cpp's own --fit-target, as
§0 did; --expect-moe then checks §0 M4's ordering. --cpu hides every GPU.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import yaml

PASSPHRASE = "pb1-disposable-passphrase"
HIDE_GPUS = {"CUDA_VISIBLE_DEVICES": "-1", "HIP_VISIBLE_DEVICES": "-1", "ROCR_VISIBLE_DEVICES": "-1"}


def serve(root: Path, port: int) -> None:
    import uvicorn
    from eugene_plexus_agent.app import create_app
    from eugene_plexus_agent.settings import Settings

    app = create_app(
        settings=Settings(config_file=root / "agent.yaml", bind_port=port, default_topology=False)
    )
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False))

    async def run() -> None:
        task = asyncio.create_task(server.serve())
        while not task.done() and not (root / "stop").exists():
            await asyncio.sleep(0.1)
        server.should_exit = True
        await task

    asyncio.run(run())


def ok(message: str) -> None:
    print(f"PASS {message}", flush=True)


def main(args: argparse.Namespace) -> None:
    server, model = args.server.resolve(), args.model.resolve()
    busy_model = args.busy_model.resolve() if args.busy_model else None
    assert server.is_file(), server
    assert model.is_file(), model
    env_gpu = HIDE_GPUS if args.cpu else {}
    # A combined CUDA+Vulkan build sees one card twice (CUDA0 and Vulkan0);
    # §0 measured with `-dev CUDA0`, so the run can pin the same.
    placement_flags = {"devices": args.devices} if args.devices else {}
    with tempfile.TemporaryDirectory(prefix="ep-pb1-") as directory:
        root = Path(directory)
        (root / "agent.yaml").write_text(
            yaml.safe_dump(
                {"engineBinaryRoots": [str(server.parent)], "securityMode": "prompt_on_startup"}
            ),
            encoding="utf-8",
        )
        from eugene_plexus_agent.library_folders import (
            FOLDERS_FILE,
            FolderRecord,
            LibraryFolderCache,
        )

        folders = {str(model.parent)} | ({str(busy_model.parent)} if busy_model else set())
        LibraryFolderCache(root / FOLDERS_FILE).update(
            [FolderRecord(f) for f in sorted(folders)], library_url="http://fixture.invalid"
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
        env["PYTHONUNBUFFERED"] = "1"
        log = (root / "agent.log").open("w", encoding="utf-8")
        process = None

        def boot() -> subprocess.Popen:
            (root / "stop").unlink(missing_ok=True)
            proc = subprocess.Popen(
                [sys.executable, __file__, "--serve", str(root), "--port", str(port)],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            for _ in range(300):
                try:
                    url = f"http://127.0.0.1:{port}/healthz"
                    if httpx.get(url, trust_env=False).status_code == 200:
                        return proc
                except httpx.HTTPError:
                    pass
                if proc.poll() is not None:
                    raise AssertionError("agent exited during startup")
                time.sleep(0.1)
            proc.kill()
            proc.wait()
            raise AssertionError("agent did not start")

        try:
            process = boot()
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(base_url=base, timeout=60, trust_env=False) as client:

                def check(response: httpx.Response, code: int = 200):  # type: ignore[no-untyped-def]
                    assert response.status_code == code, (response.status_code, response.text)
                    return response.json()

                login = check(client.post("/v1/auth/initialize", json={"passphrase": PASSPHRASE}))
                client.headers["Authorization"] = f"Bearer {login['sessionToken']}"

                def status(name: str) -> dict:
                    return check(client.get(f"/v1/runtimes/{name}"))

                def wait_status(name: str, wanted: set[str], seconds: float) -> dict:
                    deadline = time.perf_counter() + seconds
                    while time.perf_counter() < deadline:
                        runtime = status(name)
                        if runtime["status"] in wanted:
                            return runtime
                        time.sleep(1)
                    raise AssertionError(f"{name} never reached {wanted}: {status(name)}")

                stop_list: list[str] = []
                if busy_model:
                    busy = {
                        "name": "busy",
                        "engine": "llama_cpp",
                        "modelPath": str(busy_model),
                        "binary": str(server),
                        "flags": {
                            "contextSize": 2048,
                            "gpuLayers": 0 if args.cpu else 99,
                            **placement_flags,
                        },
                        "env": env_gpu,
                    }
                    check(client.post("/v1/runtimes", json=busy), 201)
                    wait_status("busy", {"ready"}, 300)
                    ok("a real runtime is serving before the build")
                    stop_list = ["busy"]

                body = {
                    "modelId": "pb1-acceptance",
                    "profileId": None,
                    "runtime": {
                        "name": "pb1-acceptance",
                        "engine": "llama_cpp",
                        "modelPath": str(model),
                        "binary": str(server),
                        "flags": dict(placement_flags),
                        "env": env_gpu,
                    },
                    "accuracy": args.accuracy,
                    "memoryMarginMiB": args.margin,
                }

                # 1. The question, asked without changing anything.
                answer = check(client.post("/v1/profile-builds/preflight", json=body))
                assert answer["problems"] == [], answer
                assert answer["runningRuntimes"] == stop_list, answer
                assert answer["estimateSeconds"] and answer["estimateSeconds"] > 0, answer
                ok(f"preflight lists {stop_list or 'nothing'} running, estimates {answer['estimateSeconds']} s")

                # 2. Not agreed: refused, nothing stopped.
                if busy_model:
                    refused = client.post("/v1/profile-builds", json=body)
                    assert refused.status_code == 409 and "busy" in refused.text, refused.text
                    assert status("busy")["status"] == "ready"
                    ok("a running model nobody agreed to stop refuses the build and keeps serving")

                # 3. Agreed: stopped for the measurement, launches held.
                started = check(
                    client.post("/v1/profile-builds", json=body | {"stopRuntimes": stop_list}), 202
                )
                t0 = time.perf_counter()
                if busy_model:
                    runtime = status("busy")
                    assert runtime["status"] == "stopped", runtime
                    assert runtime["stopReason"] == "measurement", runtime
                    assert client.post("/v1/runtimes/busy/start").status_code == 409
                    ok("the agreed model is stopped with reason `measurement`; a start waits for the build")

                # 4. The build, to the end.
                job = started
                while job["state"] == "running":
                    time.sleep(2)
                    job = next(
                        j
                        for j in check(client.get("/v1/profile-builds"))["builds"]
                        if j["id"] == started["id"]
                    )
                    if time.perf_counter() - t0 > 1800:
                        raise AssertionError("the build outlived its 30-minute limit")
                elapsed = time.perf_counter() - t0
                if args.report:
                    args.report.write_text(json.dumps(job, indent=2), encoding="utf-8")
                assert job["state"] == "completed", job["detail"]
                assert job["phase"] == "finished"
                ok(f"the build completed in {elapsed:.0f} s: {job['detail']}")

                # 5. Quality: measured on this model, the level's rule applied.
                thresholds = {"high": 96.5, "medium": 92.0}
                if args.accuracy == "max":
                    assert job["quality"] == [], job["quality"]
                    assert {c["cacheType"] for c in job["candidates"]} == {"f16"}
                    ok("Max measured no quality and never quantised the cache")
                else:
                    lower = {"high": ["q8_0"], "medium": ["q8_0", "q4_0"]}[args.accuracy]
                    assert [q["cacheType"] for q in job["quality"]] == lower, job["quality"]
                    for q in job["quality"]:
                        assert 50 < q["sameTopTokenPercent"] <= 100, q
                        assert q["tokensScored"] >= 8192, q
                        rule = q["sameTopTokenPercent"] - q["standardError"] >= thresholds[args.accuracy]
                        assert q["passes"] == rule, q
                        assert (q["cacheType"] in job["allowedCacheTypes"]) == q["passes"], job
                    for q in job["quality"]:
                        print(
                            f"     {q['cacheType']}: same top token {q['sameTopTokenPercent']:.2f}% "
                            f"± {q['standardError']:.2f}, KLD {q['meanKld']:.4f}, passes {q['passes']}"
                        )
                    ok("each lower cache's quality was measured and the level's rule applied")

                # 6. Candidates: placed by fit, measured, one confirmed.
                measured = [c for c in job["candidates"] if c.get("decodeTokensPerSecond")]
                assert measured, job["candidates"]
                for c in job["candidates"]:
                    print(
                        f"     {c['contextSize']:>7} {c['cacheType']:>5} "
                        f"decode {c.get('decodeTokensPerSecond') or 0:7.1f} "
                        f"deep {c.get('deepDecodeTokensPerSecond') or 0:7.1f} "
                        f"frontier {c.get('onFrontier')} confirmed {c.get('confirmed')} "
                        f"placement {' '.join(c['placement'])[:60]}"
                    )
                assert all(c["cacheType"] in job["allowedCacheTypes"] for c in job["candidates"])
                chosen = job["candidates"][job["recommended"]]
                assert chosen["confirmed"] is True and chosen["onFrontier"] is True, chosen
                ok(
                    f"{len(measured)} candidates measured; suggested {chosen['contextSize']:,} "
                    f"tokens, {chosen['cacheType']}, confirmed in llama-server"
                )
                assert {c["deepDepth"] for c in measured} == {2048}, "compared at one depth"
                if len({tuple(c["placement"]) for c in measured}) == 1:
                    # Nothing moved between rungs, so a longer context costs
                    # nothing at the same depth: the longest must be suggested.
                    assert chosen["contextSize"] == max(c["contextSize"] for c in measured), chosen
                    ok("every rung placed alike, so the longest context was suggested")

                if args.expect_moe:
                    by = {(c["contextSize"], c["cacheType"]): c for c in measured}
                    assert any("-ot" in c["placement"] for c in measured), "no expert offload"
                    short, long_ = by.get((4096, "f16")), by.get((65536, "f16"))
                    assert short and long_, sorted(by)
                    assert long_["deepDecodeTokensPerSecond"] < short["deepDecodeTokensPerSecond"]
                    ok("§0 M4 reproduced: experts offloaded, and 64k is slower than 4k")
                    if "q8_0" in job["allowedCacheTypes"]:
                        # Allowed, and at 64k it places differently from f16,
                        # so it must be a candidate of its own, and faster.
                        q8 = by.get((65536, "q8_0"))
                        assert q8, "q8_0 allowed but absent at 64k"
                        assert q8["deepDecodeTokensPerSecond"] > long_["deepDecodeTokensPerSecond"]
                        ok("§0 M4 reproduced: the 8-bit cache is faster than f16 at 64k")
                    else:
                        # A check that cannot run must not print PASS.
                        print("NOT CHECKED the 8-bit cache at 64k: this accuracy level refused it")

                # 7. What was stopped came back.
                if busy_model:
                    assert [(r["name"], r["state"]) for r in job["restarts"]] == [
                        ("busy", "restarted")
                    ], job["restarts"]
                    wait_status("busy", {"ready"}, 300)
                    ok("the stopped model was started again and is serving")

                # 8. A custom text too short for the quality check is refused with its count.
                short_text = "A short text about nothing in particular. " * 40
                probe = body | {"accuracy": "high", "evaluationText": short_text}
                if busy_model:
                    probe["stopRuntimes"] = stop_list
                pre = check(client.post("/v1/profile-builds/preflight", json=probe))
                assert any("too short" in p for p in pre["problems"]), pre
                short_job = check(client.post("/v1/profile-builds", json=probe), 202)
                while short_job["state"] == "running":
                    time.sleep(1)
                    short_job = next(
                        j
                        for j in check(client.get("/v1/profile-builds"))["builds"]
                        if j["id"] == short_job["id"]
                    )
                assert short_job["state"] == "failed", short_job
                assert "tokens" in short_job["detail"] and "8,192" in short_job["detail"], short_job
                assert short_job["evaluation"]["source"] == "custom"
                ok(f"a short custom text is refused with its count: {short_job['detail']}")
                if busy_model:
                    wait_status("busy", {"ready"}, 300)

                # 9. History survives the agent.
                (root / "stop").touch()
                process.wait(timeout=60)
                process = boot()
                login = check(client.post("/v1/auth/login", json={"passphrase": PASSPHRASE}))
                client.headers["Authorization"] = f"Bearer {login['sessionToken']}"
                kept = check(client.get("/v1/profile-builds"))["builds"]
                again = next(j for j in kept if j["id"] == started["id"])
                assert again["candidates"] == job["candidates"]
                ok("the build's history survives a real agent restart")
        except BaseException:
            log.flush()
            print((root / "agent.log").read_text(encoding="utf-8", errors="replace")[-8000:])
            raise
        finally:
            (root / "stop").touch()
            if process is not None:
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    process.kill()
            log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--server", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--busy-model", type=Path)
    parser.add_argument("--accuracy", default="medium", choices=["max", "high", "medium"])
    parser.add_argument("--margin", type=int)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--devices", help="llama.cpp device names for the profile, e.g. CUDA0")
    parser.add_argument("--expect-moe", action="store_true")
    parser.add_argument("--report", type=Path)
    parsed = parser.parse_args()
    if parsed.serve:
        serve(parsed.serve, parsed.port)
    else:
        main(parsed)
