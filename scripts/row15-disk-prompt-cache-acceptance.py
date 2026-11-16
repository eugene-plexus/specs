"""Row 15 (DI2, call DI-C4): the prompt cache on disk, with a real llama.cpp engine.

The agent's own `RuntimeSupervisor` runs the llama.cpp CPU build it acquires (as DI7's
acceptance does) on the tiny Stories15M model, on an OS-assigned loopback port that is never
8079-8083 or 8279-8283, with every `EUGENE_PLEXUS_*`, `LLAMA_ARG_*` and `GGML_*` variable
cleared and all state in the output folder. Do not run it against a live install.

Checks:
 1. a launch saves into its own folder in the agent's private prompt-cache folder (0700 on
    Linux and macOS), in front of the runtime's own extra arguments;
 2. a planned stop saves each conversation the engine's slots hold, as finished files only
    (0600), in that folder and nowhere else;
 3. the next start reads them back before the runtime is ready: the same two prompts then
    reuse their cached tokens (`timings.cache_n`) instead of reading them again;
 4. a changed launch (another context size) reads nothing back from the old one's files;
 5. a file unused for longer than its days is deleted and never read back;
 6. turned off, the setting passes no folder and deletes every file; Clear deletes every
    file; deleting the runtime deletes its folder.

`--sabotage` then makes every launch share one key (the check of step 4 removed), in a copy
of the agent's own `disk_prompt_cache.py`, and requires step 4 to fail; the file is restored
from its copy and compared byte for byte.

`--model-url` runs the same checks on another GGUF (a hybrid model, say) and records its
numbers; the numbers recorded are timings, never the conversations.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
MODEL_URL = "https://huggingface.co/ggml-org/models/resolve/main/tinyllamas/stories15M-q4_0.gguf"
NEVER = set(range(8079, 8084)) | set(range(8279, 8284))
RUNTIME = "r15"
# Two conversations, long enough that reading one again is measurable on a CPU.
ONE = "Once upon a time, a little robot found a bright blue stone by the river. " * 4
TWO = "The old cat slept in the sun all afternoon while the children played ball. " * 4
SAVED = "the saved prompt"
#: What the agent logged about the prompt cache on disk, with when.
LOG: list[tuple[float, str]] = []


class _Record(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage()
        if "conversation" in text:
            LOG.append((record.created, text))


def load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / name)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clean_environment() -> None:
    """No install's settings reach the supervisor or the engine."""
    for key in list(os.environ):
        if key.upper().startswith(("EUGENE_PLEXUS_", "LLAMA_ARG_", "GGML_")):
            del os.environ[key]


def free_port() -> int:
    port = load("s8-ui-acceptance.py").free_port()
    assert port not in NEVER, port
    return port


async def download(url: str, target: Path) -> None:
    if target.exists():
        return
    part = target.with_suffix(".download")
    async with httpx.AsyncClient(follow_redirects=True, timeout=600) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with part.open("wb") as out:
                async for chunk in response.aiter_bytes():
                    out.write(chunk)
    with part.open("rb") as source:
        assert source.read(4) == b"GGUF", f"{url} is not a GGUF"
    part.replace(target)


class Run:
    """One agent's runtime supervisor over the real engine, and what the checks saw."""

    def __init__(self, root: Path, build: Any, model: Path, result: dict[str, Any]) -> None:
        from eugene_plexus_agent import disk_prompt_cache as dpc
        from eugene_plexus_agent.runtimes import RuntimeSupervisor

        self.dpc = dpc
        self.root = root
        self.cache_root = root / "agent" / dpc.FOLDER_NAME
        self.model = model
        self.result = result
        self.config: dict[str, Any] = {
            "engineBinaryRoots": [str(build.binary.parent)],
            "allowUnrestrictedEngineLaunch": True,
            dpc.ENABLED_KEY: True,
            dpc.DAYS_KEY: 3,
            dpc.CAP_KEY: 20,
        }
        self.supervisor = RuntimeSupervisor(
            get_config=self.config.get, prompt_cache_root=self.cache_root
        )
        self.port = free_port()
        self.flags: dict[str, Any] = {
            "parallelSlots": 2,
            "gpuLayers": 0,
            "contextSize": 2048,
            "reuseRepeatedText": False,
        }
        self.binary = build.binary
        self.specs: list[Any] = []
        self.base = f"http://127.0.0.1:{self.port}"

    def spec(self) -> Any:
        from eugene_plexus_agent._generated.models import RuntimeSpec

        return RuntimeSpec(
            name=RUNTIME,
            engine="llama_cpp",
            modelPath=str(self.model),
            binary=str(self.binary),
            host="127.0.0.1",
            port=self.port,
            autoDriver=False,
            flags=dict(self.flags),
            extraArgs=["--threads", "2", "--threads-batch", "2"],
        )

    async def start(self) -> Any:
        spec = self.spec()
        self.specs[:] = [spec]
        self.supervisor.add_and_start(spec)
        await self.supervisor.start_readiness_loop(lambda: list(self.specs))
        LOG.clear()
        deadline = time.perf_counter() + 180
        while time.perf_counter() < deadline:
            runtime = self.supervisor.compose(spec)
            assert runtime.status.value not in ("crashed", "exited"), runtime.lastError
            if runtime.status.value == "ready":
                ready_at = time.time()
                runtime_json = runtime.model_dump(mode="json")
                # The agent's own record of reading back, and whether it came first.
                runtime_json["readBack"] = [
                    (at <= ready_at, text) for at, text in LOG if "back in" in text
                ]
                return runtime_json
            await asyncio.sleep(0.02)
        raise AssertionError(f"not ready: {self.supervisor.compose(spec).model_dump(mode='json')}")

    async def stop(self) -> float:
        from eugene_plexus_agent._generated.models import StopReason

        started = time.perf_counter()
        await self.supervisor.stop_one(RUNTIME, reason=StopReason.idle)
        return time.perf_counter() - started

    async def ask(self, client: httpx.AsyncClient, prompt: str) -> dict[str, Any]:
        response = await client.post(
            self.base + "/completion",
            json={"prompt": prompt, "n_predict": 4, "temperature": 0, "cache_prompt": True},
        )
        response.raise_for_status()
        timings = response.json().get("timings") or {}
        return {
            "cached": int(timings.get("cache_n") or 0),
            "read": int(timings.get("prompt_n") or 0),
            "promptMs": float(timings.get("prompt_ms") or 0.0),
        }

    def files(self) -> list[Path]:
        return sorted(self.cache_root.rglob("*.bin")) if self.cache_root.exists() else []

    def folder(self, runtime: dict[str, Any]) -> Path | None:
        return self.dpc.folder_of(runtime.get("argv") or [])


async def checks(run: Run, only: str | None) -> None:
    dpc = run.dpc
    record = run.result["checks"]
    async with httpx.AsyncClient(timeout=300, trust_env=False) as client:
        # 1. Its own folder, in front of the runtime's own extra arguments.
        first = await run.start()
        folder = run.folder(first)
        assert folder is not None, first["argv"]
        assert folder.parent == run.cache_root / RUNTIME, folder
        argv = first["argv"]
        assert argv[-6:-4] == [dpc.FLAG, str(folder)], argv
        if os.name != "nt":
            for path in (run.cache_root, run.cache_root / RUNTIME, folder):
                assert path.stat().st_mode & 0o777 == 0o700, (path, oct(path.stat().st_mode))
        assert first["diskPromptCache"]["saving"] is True, first["diskPromptCache"]
        record["1 own folder"] = "passed"

        # 2. A planned stop saves each conversation, finished files only, nowhere else.
        cold_one = await run.ask(client, ONE)
        cold_two = await run.ask(client, TWO)
        warm_one = await run.ask(client, ONE + " " + SAVED)
        assert warm_one["cached"] > 0, f"the engine reuses nothing even while it runs: {warm_one}"
        stop_seconds = await run.stop()
        saved = run.files()
        assert len(saved) == 2, f"expected one file per conversation, found {saved}"
        assert all(path.parent == folder for path in saved), saved
        assert not list(run.cache_root.rglob("*.part")), "an unfinished save was left"
        if os.name != "nt":
            assert all(path.stat().st_mode & 0o777 == 0o600 for path in saved), saved
        assert not list(run.model.parent.glob("*.bin")), "a file was written beside the model"
        record["2 saved at a planned stop"] = "passed"

        # 3. Read back before it is ready; the same prompts reuse their tokens.
        again = await run.start()
        assert run.folder(again) == folder, "the same launch got another folder"
        assert again["readBack"] and all(first for first, _ in again["readBack"]), (
            f"it was reported ready before reading back: {again['readBack']}"
        )
        assert "read 2 of 2" in again["readBack"][0][1], again["readBack"]
        restored_one = await run.ask(client, ONE + " " + SAVED)
        restored_two = await run.ask(client, TWO)
        assert restored_one["cached"] >= cold_one["read"] // 2, (
            f"conversation one was read again after the restart: {restored_one}"
        )
        assert restored_two["cached"] >= cold_two["read"] // 2, (
            f"conversation two was read again after the restart: {restored_two}"
        )
        run.result["measured"] = {
            "coldPrompt": cold_one,
            "afterReadBack": restored_one,
            "stopSecondsWithSave": round(stop_seconds, 3),
            "bytesSaved": sum(p.stat().st_size for p in saved),
        }
        record["3 read back before ready"] = "passed"
        await run.stop()

        # 4. A changed launch reads nothing back from the old launch's files.
        run.flags["contextSize"] = 4096
        changed = await run.start()
        other = run.folder(changed)
        fresh = await run.ask(client, ONE + " " + SAVED)
        assert other != folder and fresh["cached"] == 0, (
            f"a launch with another context size read back the old launch's files: "
            f"folder {other} (was {folder}), {fresh}"
        )
        assert len(list(folder.glob("*.bin"))) == 2, "the old launch's files were not kept"
        record["4 a changed launch reads nothing back"] = "passed"
        await run.supervisor.remove_and_stop(RUNTIME, keep_conversations=True)
        run.flags["contextSize"] = 2048
        if only == "mismatch":
            return

        # 5. Unused for longer than its days: deleted, never read back.
        old = time.time() - (3 * 86400 + 600)
        for path in folder.glob("*.bin"):
            os.utime(path, (old, old))
        expired = await run.start()
        late = await run.ask(client, ONE + " " + SAVED)
        assert late["cached"] == 0, f"an expired file was read back: {late}"
        assert not list(folder.glob("*.bin")) or all(
            time.time() - p.stat().st_mtime < 3600 for p in folder.glob("*.bin")
        ), "an expired file was kept"
        assert run.folder(expired) == folder
        record["5 expired files are deleted"] = "passed"

        # 6. Off passes nothing and deletes every file; Clear; a deleted runtime.
        await run.stop()
        assert run.files(), "nothing was saved before turning it off"
        run.config[dpc.ENABLED_KEY] = False
        await run.supervisor.sweep_prompt_cache([RUNTIME])
        assert not run.files(), "turning it off left files"
        off = await run.start()
        assert dpc.FLAG not in off["argv"], off["argv"]
        assert off["diskPromptCache"]["saving"] is False, off["diskPromptCache"]
        await run.ask(client, ONE)
        await run.stop()
        assert not run.files(), "a stop saved with the setting off"
        run.config[dpc.ENABLED_KEY] = True
        await run.start()
        await run.ask(client, ONE)
        await run.stop()
        assert run.files()
        cleared = run.supervisor.clear_prompt_cache()
        assert cleared.conversations >= 1 and not run.files(), cleared
        await run.start()
        await run.ask(client, TWO)
        await run.stop()
        assert run.files()
        await run.supervisor.remove_and_stop(RUNTIME)
        assert not (run.cache_root / RUNTIME).exists(), "the runtime's folder outlived it"
        record["6 off, Clear and a deleted runtime delete the files"] = "passed"


async def main(args: argparse.Namespace) -> None:
    clean_environment()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        handlers=[
            logging.FileHandler(root / "agent.log", encoding="utf-8"),
            logging.StreamHandler(),
            _Record(),
        ],
    )
    result: dict[str, Any] = {"modelUrl": args.model_url, "checks": {}}
    run: Run | None = None
    try:
        from eugene_plexus_agent._http import aclose_shared

        engines = args.engines or (root.parent / (root.name + "-engine"))
        build = await load("di7-same-answer-acceptance.py").acquire(engines)
        result["build"] = {"version": build.version, "variant": build.variant}
        models = args.models or root
        models.mkdir(parents=True, exist_ok=True)
        model = models / args.model_url.rsplit("/", 1)[1]
        await download(args.model_url, model)
        run = Run(root, build, model, result)
        await checks(run, args.only)
        result["passed"] = True
    except BaseException as exc:
        result["passed"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if run is not None:
            await run.supervisor.stop_all()
        await aclose_shared()
        (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        if not args.models and args.model_url == MODEL_URL:
            # The evidence is small; weights are not CI artifacts.
            for path in root.glob("*.gguf"):
                path.unlink()


def sabotage(args: argparse.Namespace) -> None:
    """Every launch shares one key, in a copy of the agent's own file: step 4 must fail."""
    import eugene_plexus_agent.disk_prompt_cache as target

    source = Path(target.__file__)
    original = source.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    backup = args.output.resolve() / "disk_prompt_cache.py.copy"
    args.output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, backup)
    marker = b'return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]'
    assert original.count(marker) == 1, "the key's return line moved: update the sabotage"
    try:
        source.write_bytes(original.replace(marker, b'return "0" * 32'))
        for cached in (source.parent / "__pycache__").glob("disk_prompt_cache*.pyc"):
            cached.unlink()
        command = [
            sys.executable,
            __file__,
            "--only",
            "mismatch",
            "--output",
            str(args.output.resolve() / "sabotaged"),
            "--model-url",
            args.model_url,
            "--engines",
            str(args.engines or (args.output.resolve().parent / (args.output.name + "-engine"))),
            "--models",
            str(args.output.resolve() / "models"),
        ]
        sabotaged = subprocess.run(command, capture_output=True, text=True, timeout=1200)
        tail = (sabotaged.stdout + sabotaged.stderr)[-3000:]
        assert sabotaged.returncode != 0, f"the sabotaged key check passed:\n{tail}"
        assert "read back the old launch's files" in tail, f"it failed for another reason:\n{tail}"
        print("sabotage: a shared key read back another launch's files, and step 4 failed")
    finally:
        shutil.copyfile(backup, source)
        for cached in (source.parent / "__pycache__").glob("disk_prompt_cache*.pyc"):
            cached.unlink()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest, "restore failed"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-url", default=MODEL_URL)
    parser.add_argument("--only", choices=["mismatch"], default=None)
    parser.add_argument("--engines", type=Path, default=None)
    parser.add_argument("--models", type=Path, default=None)
    parser.add_argument("--sabotage", action="store_true")
    parsed = parser.parse_args()
    if parsed.sabotage:
        if parsed.models is None:
            parsed.models = parsed.output.resolve() / "models"
        asyncio.run(main(parsed))
        sabotage(parsed)
    else:
        asyncio.run(main(parsed))
