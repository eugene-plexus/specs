"""Progress sabotage pass: put each hole back and prove a check notices.

2026-09-27: a stream says what the backend is doing before and between
its output -- llama.cpp's prompt reading, a hosted API holding the
request, Claude Code's and Codex's own tools -- and the model's thinking
reaches the page instead of being discarded.

Restores from a COPY, never `git checkout --`, and opens with a baseline
assertion that every gate passes unsabotaged (memory:
`sabotage-runs-restore-from-a-copy`).
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("D:/py/eugene-plexus")
HTTP = ("inference-driver", "src/eugene_plexus_inference_driver/engines/openai_compat_http.py")
CLAUDE = ("inference-driver", "src/eugene_plexus_inference_driver/engines/claude_code_cli.py")
CODEX = ("inference-driver", "src/eugene_plexus_inference_driver/engines/codex_cli.py")
ROUTE = ("inference-driver", "src/eugene_plexus_inference_driver/routes/generate.py")
TIERED = ("gateway", "src/eugene_plexus_gateway/driver_client.py")
DOOR = ("gateway", "src/eugene_plexus_gateway/routes/inference.py")
CONTRACT = ("gateway", "src/eugene_plexus_gateway/chat_contract.py")
COMPLETIONS = ("ui", "src/lib/completions.ts")
TRANSCRIPT = ("ui", "src/lib/playgroundTranscript.ts")
WORKING = ("ui", "src/lib/workingState.ts")
CHATLOG = ("ui", "src/components/ChatLog.tsx")
PLAYGROUND = ("ui", "src/app/playground/page.tsx")
TRYIT = ("ui", "src/components/home/TryItCard.tsx")
TIMEOUT = 900

# (label, (repo, file), old, new)
SABOTAGES: list[tuple[str, tuple[str, str], str, str]] = [
    # --- the driver: llama.cpp and every HTTP backend ------------------------
    (
        "llama.cpp's flag is sent to any backend, a hosted API included",
        HTTP,
        "        if report and await self._answers_as_llama_cpp():\n",
        "        if report:\n",
    ),
    (
        "llama.cpp's flag is sent when nobody asked",
        HTTP,
        "        if report and await self._answers_as_llama_cpp():\n",
        "        if await self._answers_as_llama_cpp():\n",
    ),
    (
        "a backend that could not be asked counts as llama.cpp",
        HTTP,
        "        return self._llama_cpp is True\n",
        "        return self._llama_cpp is not False\n",
    ),
    (
        "a llama-server still loading is cached as not llama.cpp (found live)",
        HTTP,
        "        if response.status_code in _NO_SUCH_PATH:\n",
        "        if response.status_code >= 400:\n",
    ),
    (
        "the context probe does not remember what /props said",
        HTTP,
        "        found = value if isinstance(value, int) and value > 0 else None\n"
        "        self._llama_cpp = found is not None\n",
        "        found = value if isinstance(value, int) and value > 0 else None\n",
    ),
    (
        "a progress frame arms the stall clock",
        HTTP,
        "                    else:\n                        saw_first_data = True\n                    served_model",
        "                    saw_first_data = True\n                    served_model",
    ),
    (
        "prompt progress is yielded to a caller that did not ask",
        HTTP,
        "                        if report:\n                            progress = _prompt_progress(read)",
        "                        if True:\n                            progress = _prompt_progress(read)",
    ),
    (
        "the response opening says nothing",
        HTTP,
        "                    yield Chunk(progress=StreamProgress(stage=Stage.working))\n"
        "                lines = response.aiter_lines()\n",
        "                    pass\n                lines = response.aiter_lines()\n",
    ),
    (
        "every keepalive comment is its own frame",
        HTTP,
        "                        if now - last_keepalive >= _KEEPALIVE_PROGRESS_SECONDS:\n",
        "                        if True:\n",
    ),
    (
        "the cached count is dropped",
        HTTP,
        '        cachedTokens=count("cache"),\n',
        "",
    ),
    # --- the driver: the route -----------------------------------------------
    (
        "progress is framed as a token",
        ROUTE,
        '        return f"event: progress\\ndata: {progress.model_dump_json(exclude_none=True)}\\n\\n"\n',
        '        return f"event: token\\ndata: {progress.model_dump_json(exclude_none=True)}\\n\\n"\n',
    ),
    # --- the driver: Claude Code ---------------------------------------------
    (
        "Claude's thinking is read past again",
        CLAUDE,
        "                if show_reasoning and isinstance(thought, str) and thought:\n"
        "                    thoughts.append(thought)\n"
        "                    yield Chunk(reasoning=thought)\n",
        "                pass\n",
    ),
    (
        "Claude's thinking is shown with thinking off",
        CLAUDE,
        '        show_reasoning = self._thinking_mode != "off"\n\n        async for line in stream_cli_lines(',
        "        show_reasoning = True\n\n        async for line in stream_cli_lines(",
    ),
    (
        "Claude's tools are not reported",
        CLAUDE,
        '                if report and block.get("type") == "tool_use":\n',
        "                if False:\n",
    ),
    (
        "Claude's start and requests are not reported",
        CLAUDE,
        '                if report and event.get("subtype") in ("init", "status"):\n',
        "                if False:\n",
    ),
    # --- the driver: Codex ---------------------------------------------------
    (
        "Codex's own reason is dropped when the stream fails",
        CODEX,
        "            if failure:\n                raise CliError(f\"codex failed: {failure}\") from e\n",
        "",
    ),
    (
        "Codex's own reason is dropped on the batch path",
        CODEX,
        "                f\"{reason or result.stderr.decode(errors='replace').strip() or '<no stderr>'}\"\n",
        "                f\"{result.stderr.decode(errors='replace').strip() or '<no stderr>'}\"\n",
    ),
    (
        "the Codex reason is the outer JSON, not the API's sentence",
        CODEX,
        "        found = nested.get(\"message\") if isinstance(nested, dict) else inner.get(\"message\")\n",
        "        found = None\n",
    ),
    (
        "Codex's tools are not reported",
        CODEX,
        "                    if report and tool is not None:\n",
        "                    if False:\n",
    ),
    # --- the gateway ---------------------------------------------------------
    (
        "progress is the commit point and the first token",
        TIERED,
        "                        if event.progress is not None:\n"
        "                            # Not output.",
        "                        if False:\n"
        "                            # Not output.",
    ),
    (
        "progress times the first token",
        TIERED,
        "                            yield event\n                            continue\n"
        "                        if first_ms is None:\n",
        "                            if first_ms is None:\n"
        "                                first_ms = int((time.perf_counter() - started) * 1000)\n"
        "                            yield event\n                            continue\n"
        "                        if first_ms is None:\n",
    ),
    (
        "the driver's progress event is read as nothing",
        TIERED,
        '                if event_name == "progress":\n'
        "                    yield StreamEvent(progress=parsed)\n"
        "                    continue\n",
        "",
    ),
    (
        "the driver is asked for progress whoever asked",
        DOOR,
        "        reportProgress=bool(body.stream_options and body.stream_options.include_progress)"
        " or None,\n",
        "        reportProgress=True,\n",
    ),
    (
        "include_progress is not held to a boolean",
        CONTRACT,
        '        for flag in ("include_usage", "include_progress"):\n',
        '        for flag in ("include_usage",):\n',
    ),
    (
        "a caller who did not ask is passed a driver's unasked progress",
        DOOR,
        "                    if progress is not None and generate.reportProgress:\n",
        "                    if progress is not None:\n",
    ),
    (
        "the role chunk goes out ahead of the progress",
        DOOR,
        "                    progress = _progress_of(event.progress)\n",
        "                    progress = _progress_of(event.progress)\n"
        "                    if not emitted_role:\n"
        "                        emitted_role = True\n"
        "                        yield frame(\n"
        "                            envelope(delta=Delta(role=Role2.assistant),"
        " finish=None, model=body.model)\n"
        "                        )\n",
    ),
    (
        "the elapsed time is dropped on the way out",
        DOOR,
        '                "elapsed_ms": raw.get("elapsedMs"),\n',
        "",
    ),
    # --- the UI: the stream reader -------------------------------------------
    (
        "a progress chunk is read as the routing envelope",
        COMPLETIONS,
        "        if (progress && noChoices) {\n",
        "        if (progress && noChoices && false) {\n",
    ),
    (
        "the thinking is read past again",
        COMPLETIONS,
        "          opts.onReasoning?.(thought);\n",
        "",
    ),
    (
        "progress is asked for whether or not anything reads it",
        COMPLETIONS,
        "  if (stream && opts.onProgress) body.stream_options = { include_progress: true };\n",
        "  if (stream) body.stream_options = { include_progress: true };\n",
    ),
    (
        "a batch request asks for progress",
        COMPLETIONS,
        "  if (stream && opts.onProgress) body.stream_options = { include_progress: true };\n",
        "  if (opts.onProgress) body.stream_options = { include_progress: true };\n",
    ),
    (
        "a progress chunk starts the first-token clock",
        COMPLETIONS,
        "        // What the backend is doing, not output: no choices, and an\n",
        "        if (report.firstFrameMs === null) {\n"
        "          report.firstFrameMs = Math.round(performance.now() - started);\n"
        "        }\n"
        "        // What the backend is doing, not output: no choices, and an\n",
    ),
    (
        "a turn that only thought is thrown away",
        COMPLETIONS,
        "  if (streamError && !content && toolCalls.length === 0 && !reasoning) {\n",
        "  if (streamError && !content && toolCalls.length === 0) {\n",
    ),
    (
        "the thinking is sent back to the model",
        TRANSCRIPT,
        "    delete wire.reasoning;\n",
        "",
    ),
    # --- the UI: what the wait says ------------------------------------------
    (
        "the cached tokens are counted as work to do",
        WORKING,
        "  const cached = Math.min(progress.cached_tokens ?? 0, total);\n",
        "  const cached = 0;\n",
    ),
    (
        "time left is guessed before there is a rate",
        WORKING,
        "  if (done > 0 && elapsed >= MIN_RATE_MS) {\n",
        "  if (done > 0 && elapsed > 0) {\n",
    ),
    (
        "the still-working sentence is said over visible thinking",
        WORKING,
        "  if (seconds < STILL_WORKING_AFTER_SECONDS || state.thinking) return false;\n",
        "  if (seconds < STILL_WORKING_AFTER_SECONDS) return false;\n",
    ),
    (
        "a sleeping model is anything with nothing ready",
        WORKING,
        "  return info?.on_demand === true && (info.ready_backends ?? 0) === 0;\n",
        "  return (info?.ready_backends ?? 1) === 0;\n",
    ),
    (
        "the thinking outranks a named tool",
        WORKING,
        '  if (progress?.stage === "tool") {\n',
        '  if (progress?.stage === "tool" && !state.thinking) {\n',
    ),
    # --- the UI: the chat log and the pages ----------------------------------
    (
        "the indicator does not come back between two parts of an answer",
        CHATLOG,
        "  const showWork = pending && (!answering || (work?.progress ?? null) !== null);\n",
        "  const showWork = pending && !answering;\n",
    ),
    (
        "an answer still arriving is called empty",
        CHATLOG,
        "        (text || images.length > 0 || (calls.length === 0 && !live)) && (\n",
        "        (text || images.length > 0 || calls.length === 0) && (\n",
    ),
    (
        "the thinking stays open after the answer",
        CHATLOG,
        "      {thinking && <Thinking text={thinking} live={live && !text} ms={message.thoughtMs} />}\n",
        "      {thinking && <Thinking text={thinking} live={true} ms={message.thoughtMs} />}\n",
    ),
    (
        "the playground does not listen for progress",
        PLAYGROUND,
        "          onProgress: (progress) => setWork((w) => (w ? { ...w, progress } : w)),\n",
        "",
    ),
    (
        "the playground does not know the model is asleep",
        PLAYGROUND,
        "      starting: isAsleep(models.find((m) => m.id === chosen)),\n",
        "      starting: false,\n",
    ),
    (
        "Home does not listen for progress",
        TRYIT,
        "          onProgress: (progress) => setWork((w) => (w ? { ...w, progress } : w)),\n",
        "",
    ),
    (
        "Home does not show the thinking",
        TRYIT,
        "            thinking.think(delta);\n",
        "",
    ),
]

FILES = sorted({target for _, target, _, _ in SABOTAGES})


def run(repo: str) -> tuple[int, str]:
    if repo in ("inference-driver", "gateway"):
        py = ROOT / repo / ".venv" / "Scripts" / "python.exe"
        argv = [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", "tests"]
    elif repo == "ui":
        argv = [
            "npx.cmd",
            "vitest",
            "run",
            "src/lib/completions",
            "src/lib/workingState",
            "src/lib/playgroundTranscript",
            "src/components/ChatLog",
            "src/components/home/TryItCard",
            "src/app/playground",
            "src/app/page.test.tsx",
        ]
    else:
        raise SystemExit(f"no gate for {repo}")
    try:
        done = subprocess.run(
            argv,
            cwd=ROOT / repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            env={**os.environ, "MSYS_NO_PATHCONV": "1"},
        )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    only = sys.argv[1:]
    sabotages = [s for s in SABOTAGES if not only or any(o in s[0] for o in only)]
    repos = sorted({repo for _, (repo, _), _, _ in sabotages})

    backup = Path(tempfile.mkdtemp(prefix="progress-sabotage-"))
    for repo, relative in FILES:
        destination = backup / repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / repo / relative, destination)
    print(f"copy in {backup}\n")

    for repo in repos:
        code, out = run(repo)
        print(f"[baseline {repo}] {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    print()

    caught = escaped = 0
    for label, (repo, relative), old, new in sabotages:
        path = ROOT / repo / relative
        source = io.open(path, encoding="utf-8", newline="").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="").write(source.replace(old, new, 1))
        try:
            code, _ = run(repo)
        finally:
            shutil.copy2(backup / repo / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(sabotages)} sabotages")
    for repo in repos:
        code, out = run(repo)
        print(f"[restored {repo}] {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
