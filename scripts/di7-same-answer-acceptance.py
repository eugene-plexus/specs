"""DI7: real acquired llama.cpp CPU engine, ten fixed-seed answers under load.

Uses the shared s8 harness's safe ports and CX9's tiny Stories15M test model.
Runs both settings, retains every answer, launch and server log. Only the on
case must repeat: the off case records what happened, including repetition.
GPU and vLLM measurements belong to a separate live run on suitable hardware.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import platform
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
MODEL_URL = "https://huggingface.co/ggml-org/models/resolve/main/tinyllamas/stories15M-q4_0.gguf"
PROMPT = "Once upon a time, a little robot found a bright blue stone."
SEED = 4720


def answer_record(answers: list[str]) -> dict:
    return {
        "answers": answers,
        "sha256": [hashlib.sha256(a.encode("utf-8")).hexdigest() for a in answers],
        "uniqueAnswers": len(set(a.encode("utf-8") for a in answers)),
    }


def check_answers(enabled: bool, record: dict) -> None:
    assert len(record["answers"]) == 10, (
        f"expected 10 answers, got {len(record['answers'])}"
    )
    assert all(record["answers"]), "engine returned an empty answer"
    if enabled:
        assert record["uniqueAnswers"] == 1, (
            f"Same answer every time on produced {record['uniqueAnswers']} distinct answers"
        )


def harness():
    spec = importlib.util.spec_from_file_location("s8", HERE / "s8-ui-acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def acquire(root: Path):
    from eugene_plexus_agent._generated.models import (
        Accelerator,
        Arch,
        EngineKind,
        HostAccelerator,
        Os,
    )
    from eugene_plexus_agent.engines.acquisition import (
        EngineInstaller,
        ManagedStore,
        Unavailable,
    )
    from eugene_plexus_agent.engines.llama_cpp import LlamaCppAdapter

    # Explicit CPU selection: do not probe or occupy any graphics card.
    host = HostAccelerator(
        os=Os(platform.system().lower()), arch=Arch.x64, accelerator=Accelerator.none
    )
    adapter = LlamaCppAdapter()
    plan = await asyncio.to_thread(adapter.plan_latest, host)
    assert not isinstance(plan, Unavailable), (
        f"CPU engine acquisition unavailable: {plan}"
    )
    store = ManagedStore(root / "engines", EngineKind.llama_cpp)
    installer = EngineInstaller(store, EngineKind.llama_cpp)
    try:
        installer.start(plan)
        while installer.running:
            await asyncio.sleep(0.1)
        state = installer.snapshot()
        assert state and state.state.value == "done", (
            f"CPU engine acquisition failed: {state}"
        )
        build = store.current()
        assert build, "acquisition completed without an installed binary"
        return build
    finally:
        await installer.aclose()


async def under_load(
    client: httpx.AsyncClient, base: str, round_: int
) -> tuple[str, int]:
    async def complete(prompt: str, seed: int, count: int) -> str:
        response = await client.post(
            base + "/completion",
            json={
                "prompt": prompt,
                "seed": seed,
                "temperature": 0.8,
                "n_predict": count,
                "ignore_eos": True,
                "cache_prompt": False,
            },
        )
        response.raise_for_status()
        return response.json()["content"]

    others = [
        asyncio.create_task(
            complete(
                f"A different story, round {round_}, visitor {i}: "
                + "The little bird sang. " * (i + 1),
                SEED + i + round_,
                512,
            )
        )
        for i in range(3)
    ]
    try:
        # Prove that three requests reached the engine before sending the fixed
        # prompt. With one slot, two are queued; they cannot share its batch.
        deadline = time.perf_counter() + 30
        busy = 0
        while time.perf_counter() < deadline:
            for task in others:
                if task.done():
                    task.result()  # Surface an HTTP error as its observed cause.
            response = await client.get(base + "/metrics")
            response.raise_for_status()
            values = {}
            for line in response.text.splitlines():
                if line.startswith(
                    ("llamacpp:requests_processing ", "llamacpp:requests_deferred ")
                ):
                    name, value = line.split()
                    values[name] = int(float(value))
            busy = sum(values.values())
            if busy >= 3:
                break
            assert not any(t.done() for t in others), (
                f"background requests finished before three were admitted; metrics: {values}"
            )
            await asyncio.sleep(0.005)
        assert busy >= 3, (
            f"engine never reported three requests running or queued; observed {busy}"
        )
        answer = await complete(PROMPT, SEED, 48)
        await asyncio.gather(*others)
        return answer, busy
    finally:
        for task in others:
            if not task.done():
                task.cancel()
        await asyncio.gather(*others, return_exceptions=True)


async def measure(root: Path, build, model: Path, result: dict) -> None:
    from eugene_plexus_agent._generated.models import RuntimeSpec
    from eugene_plexus_agent._http import aclose_shared, client_for
    from eugene_plexus_agent.runtimes import RuntimeSupervisor

    async with client_for("http://127.0.0.1", timeout=180, trust_env=False) as client:
        for enabled in (False, True):
            supervisor = RuntimeSupervisor(
                get_config={
                    "engineBinaryRoots": [str(build.binary.parent)],
                    "allowUnrestrictedEngineLaunch": True,
                }.get
            )
            port = harness().free_port()
            spec = RuntimeSpec(
                name="di7",
                engine="llama_cpp",
                modelPath=str(model),
                binary=str(build.binary),
                host="127.0.0.1",
                port=port,
                autoDriver=False,
                flags={
                    "sameAnswerEveryTime": enabled,
                    "parallelSlots": 4,
                    "gpuLayers": 0,
                    "contextSize": 8192,
                    "cacheRam": 0,
                    "reuseRepeatedText": False,
                },
                extraArgs=["--metrics", "--threads", "2", "--threads-batch", "2"],
            )
            label = "on" if enabled else "off"
            observed = result["runs"][label] = {"answers": [], "backgroundAdmitted": []}
            try:
                supervisor.add_and_start(spec)
                await supervisor.start_readiness_loop(lambda: [spec])
                deadline = time.perf_counter() + 120
                while time.perf_counter() < deadline:
                    runtime = supervisor.compose(spec)
                    assert runtime.status.value not in ("crashed", "exited"), (
                        runtime.lastError
                    )
                    if runtime.status.value == "ready":
                        break
                    await asyncio.sleep(0.1)
                else:
                    raise AssertionError(
                        f"engine not ready: {runtime.model_dump(mode='json')}"
                    )
                observed["runtime"] = runtime.model_dump(mode="json")
                assert runtime.flags["sameAnswerEveryTime"] is enabled, observed[
                    "runtime"
                ]
                if enabled:
                    assert runtime.argv[runtime.argv.index("--parallel") + 1] == "1", (
                        runtime.argv
                    )
                    assert runtime.capabilities.parallelSlots == 1, runtime.capabilities
                base = f"http://127.0.0.1:{port}"
                for round_ in range(10):
                    answer, busy = await under_load(client, base, round_)
                    observed["answers"].append(answer)
                    observed["backgroundAdmitted"].append(busy)
                observed.update(answer_record(observed["answers"]))
                check_answers(enabled, observed)
            finally:
                await supervisor.stop_all()
    await aclose_shared()


async def run(root: Path) -> None:
    # No inherited install settings reach a supervisor or an engine.
    for key in list(os.environ):
        if key.upper().startswith(("EUGENE_PLEXUS_", "LLAMA_ARG_", "GGML_")):
            del os.environ[key]
    root.mkdir(parents=True, exist_ok=False)
    logging.basicConfig(
        level=logging.INFO,
        handlers=[
            logging.FileHandler(root / "server.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    result = {
        "engine": "llama.cpp",
        "hardware": "CPU",
        "modelUrl": MODEL_URL,
        "prompt": PROMPT,
        "seed": SEED,
        "runs": {},
    }
    try:
        build = await acquire(root.parent / (root.name + "-engine"))
        result["build"] = {"version": build.version, "variant": build.variant}
        model = root / "stories15M-q4_0.gguf"
        async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
            async with client.stream("GET", MODEL_URL) as response:
                response.raise_for_status()
                with model.open("wb") as out:
                    async for chunk in response.aiter_bytes():
                        out.write(chunk)
        with model.open("rb") as source:
            assert source.read(4) == b"GGUF", "model download is not a GGUF"
            source.seek(0)
            result["modelSha256"] = hashlib.file_digest(source, "sha256").hexdigest()
        await measure(root, build, model, result)
        result["passed"] = True
    except Exception as exc:
        result["passed"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        (root / "result.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        # The evidence is small; an engine and weights are not CI artifacts.
        if (root / "stories15M-q4_0.gguf").exists():
            (root / "stories15M-q4_0.gguf").unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.output.resolve()))
