"""Sabotage pass: embedding and reranking models started by the agent itself (MR3,
2026-10-11). Only the code that changed.

Restores from a COPY, never `git checkout --` (the work being checked is uncommitted when
this runs, and a checkout would be the end of it), opens with a baseline on every gate it
is about to use, so a "caught" is a gate that was green and went red, and ends by comparing
every file it touched with the copy byte for byte.

Gates:

- `agent-unit`: the agent's MR3 tests (`test_run_mode`, `test_chat_argv_is_unchanged`,
  `test_search_models`, `test_gguf_run_facts`, `test_run_worker`);
- `agent-chat-argv`: `test_chat_argv_is_unchanged.py` alone, the pin of every chat model's
  command line, so that "the regression test can fail" is shown by that test and no other;
- `library-unit`: the library's `tests/test_search_models.py`;
- `driver-unit`: the inference-driver's `tests/test_embeddings.py`;
- `acc-*`: `mr3-search-models-acceptance.py` over real processes and real models, with only
  the phases a break can reach (`--skip`): `core` is L (the library's reading of each file),
  A (the agent's command lines), C (what it reports) and G (the gateway); `override` adds O,
  `width` W, `idle` I, `flip` F and `rerank` R.

What this change invites, and what the pass breaks (each once):

* argv per mode: no --embeddings (the bug), a reranker started as an embedder or with no
  --reranking, --pooling added when the header names one or never added when it does not, the
  four defaults missing, a default beating the person's own flag / environment variable /
  typed argument, extraArgs no longer last, each header rule (pooling 4, other pooling,
  non-causal attention) taken away;
* auto against an explicit choice: the header beating `chat`, `embedding` or `reranking`; the
  profile's mode dropped on the way to the runtime; a run adopting a runtime declared under
  another mode;
* idle: an embedder keeping the idle timeout, start-on-demand or eviction it was declared
  with; capabilities not read off the command line;
* the Library's rerank capability from header bytes: never read, the wrong pooling number,
  labels ignored, a reranker also an embedding model, the scanner or preflight not saying it;
* the chat-argv regression test: a chat model resolved as an embedder (readable header,
  unreadable header), given a search model's defaults, or given one flag more;
* the driver and the companion: a reranker asked to embed (llama-server --reranking has
  died answering it, and the driver asked at every poll), the rerank question not kept or
  answered by a model still loading; a 503 while the model loads recorded as "does not embed"
  for the driver's life; a runtime edited to start as something else keeping the driver that
  learned the old answer, or every edit restarting it.

An escape means the checks cannot tell the fix from its opposite.

Usage: python specs/scripts/mr3-sabotage.py [--gate NAME ...] [--label TEXT ...] [--anchors]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("D:/py/eugene-plexus")
TIMEOUT = 1200

AGENT_PY = str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe")
LIBRARY_PY = str(ROOT / "library" / ".venv" / "Scripts" / "python.exe")
DRIVER_PY = str(ROOT / "inference-driver" / ".venv" / "Scripts" / "python.exe")
ACCEPTANCE = str(ROOT / "specs" / "scripts" / "mr3-search-models-acceptance.py")
SCRATCH = (
    "C:/Users/troyc/AppData/Local/Temp/claude/d--py-eugene-plexus-specs/"
    "8fdf4703-5901-4dea-a989-c9fe897eef3c/scratchpad/rag/dl"
)
MODELS = [
    "--llama-server", f"{SCRATCH}/llamacpp-bin/b11552/llama-server.exe",
    "--embedding-model", "C:/Users/troyc/.eugene-plexus/acceptance-models/nomic-embed-text-v1.5.Q8_0.gguf",
    "--qwen3-embedding", f"{SCRATCH}/gguf/Qwen3-Embedding-0.6B-Q8_0.gguf",
    "--chat-model", "C:/Users/troyc/.eugene-plexus/acceptance-models/Qwen3-0.6B-Q4_K_M.gguf",
    "--reranker", f"{SCRATCH}/gguf/qwen3-reranker-0.6b-q8_0.gguf",
]


def pytest_gate(python: str, *files: str) -> list[str]:
    return [python, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider", *files]


def acceptance(skip: str) -> list[str]:
    return [AGENT_PY, "-u", ACCEPTANCE, *MODELS, *(["--skip", skip] if skip else [])]


GATES: dict[str, tuple[str, list[str]]] = {
    "agent-unit": (
        "agent",
        pytest_gate(
            AGENT_PY,
            "tests/test_run_mode.py",
            "tests/test_chat_argv_is_unchanged.py",
            "tests/test_search_models.py",
            "tests/test_gguf_run_facts.py",
            "tests/test_run_worker.py",
        ),
    ),
    "agent-chat-argv": ("agent", pytest_gate(AGENT_PY, "tests/test_chat_argv_is_unchanged.py")),
    "library-unit": ("library", pytest_gate(LIBRARY_PY, "tests/test_search_models.py")),
    "driver-unit": ("inference-driver", pytest_gate(DRIVER_PY, "tests/test_embeddings.py")),
    "acc-core": ("specs", acceptance("I,W,O,F,R")),
    "acc-override": ("specs", acceptance("I,W,F,R")),
    "acc-width": ("specs", acceptance("I,O,F,R")),
    "acc-idle": ("specs", acceptance("W,O,F,R")),
    "acc-flip": ("specs", acceptance("I,W,O,R")),
    "acc-rerank": ("specs", acceptance("I,W,O,F")),
}

RUN_MODE = "agent/src/eugene_plexus_agent/engines/run_mode.py"
GGUF_CONTEXT = "agent/src/eugene_plexus_agent/gguf_context.py"
LLAMA = "agent/src/eugene_plexus_agent/engines/llama_cpp.py"
RUNTIMES = "agent/src/eugene_plexus_agent/runtimes.py"
ROUTES = "agent/src/eugene_plexus_agent/routes/runtimes.py"
RUN_WORKER = "agent/src/eugene_plexus_agent/run_worker.py"
LIB_GGUF = "library/src/eugene_plexus_library/formats/gguf.py"
LIB_SCANNER = "library/src/eugene_plexus_library/scanner.py"
LIB_PREFLIGHT = "library/src/eugene_plexus_library/preflight.py"
DRIVER = "inference-driver/src/eugene_plexus_inference_driver/engines/openai_compat_http.py"

U = ("agent-unit",)

EMBEDDINGS_ARGV = '            return ["--embeddings", *(["--pooling", self.pooling] if self.pooling else [])]\n'
RERANKING_ARGV = '        if self.task is Task.reranking:\n            return ["--reranking"]\n'
POOLING_NAMED = "    if facts.pooling_type is not None and facts.pooling_type != 0:\n        return None\n"
POOLING_LAST = '    return "mean" if facts.causal is False else "last"\n'
DEFAULT_SET = "        merged[key] = value\n    return merged\n"
CURATED_WINS = "        if merged.get(key) is not None:\n            continue\n"
ENV_WINS = '        if env is not None and env.get(variable) not in (None, ""):\n            continue\n'
TYPED_WINS = (
    '        if any(a in spellings or a.startswith(tuple(s + "=" for s in spellings)) for a in typed):\n'
    "            continue\n"
)
EXTRA_LAST = (
    "        argv += launch.argv()\n\n"
    "        # Verbatim, last, so an operator can always override something the\n"
    "        # curated surface generated above.\n"
    "        if spec.extraArgs:\n"
    "            argv += list(spec.extraArgs)\n"
    "        return argv\n"
)
EXTRA_NOT_LAST = (
    "        # Verbatim, last, so an operator can always override something the\n"
    "        # curated surface generated above.\n"
    "        if spec.extraArgs:\n"
    "            argv += list(spec.extraArgs)\n"
    "        argv += launch.argv()\n"
    "        return argv\n"
)
CHAT_FALLTHROUGH = '    return Resolved(Task.chat, "its header names no pooling and attention is causal")\n'
CHAT_UNREADABLE = '        return Resolved(Task.chat, "the file\'s header could not be read, so it starts as chat")\n'
SEARCH_DEFAULTS_IF = (
    "        if launch.search:\n"
    "            flags = run_mode.with_search_defaults(flags, spec.env, spec.extraArgs)\n"
)
COMPANION_ASKS = "            and was != await asyncio.to_thread(started_as, request, updated)\n"

# (label, gates, file, old, new)
SABOTAGES: list[tuple[str, tuple[str, ...], str, str, str]] = [
    # ---- argv per mode ----------------------------------------------------------------------
    (
        "THE BUG: an embedder is never given --embeddings",
        ("agent-unit", "acc-core"),
        RUN_MODE,
        EMBEDDINGS_ARGV,
        "            return []\n",
    ),
    (
        "a reranker is started as an embedder (--embeddings in place of --reranking)",
        ("agent-unit", "acc-rerank"),
        RUN_MODE,
        RERANKING_ARGV,
        '        if self.task is Task.reranking:\n            return ["--embeddings"]\n',
    ),
    (
        "a reranker is never given --reranking",
        U,
        RUN_MODE,
        RERANKING_ARGV,
        "        if self.task is Task.reranking:\n            return []\n",
    ),
    (
        "--pooling is added even when the header names one",
        ("agent-unit", "acc-core"),
        RUN_MODE,
        POOLING_NAMED,
        "",
    ),
    (
        "--pooling is never added, even for a header that names none",
        ("agent-unit", "acc-override"),
        RUN_MODE,
        POOLING_LAST,
        "    return None\n",
    ),
    (
        "the four defaults are not applied",
        ("agent-unit", "acc-core"),
        RUN_MODE,
        DEFAULT_SET,
        "        pass\n    return merged\n",
    ),
    (
        "a default beats the person's own curated flag",
        ("agent-unit", "acc-width"),
        RUN_MODE,
        CURATED_WINS,
        "        if False:\n            continue\n",
    ),
    (
        "a default beats the engine's own environment variable",
        U,
        RUN_MODE,
        ENV_WINS,
        "",
    ),
    (
        "a default beats a flag typed into extraArgs",
        U,
        RUN_MODE,
        TYPED_WINS,
        "",
    ),
    (
        "extraArgs are no longer last: the mode's flags come after them",
        U,
        LLAMA,
        EXTRA_LAST,
        EXTRA_NOT_LAST,
    ),
    (
        "pooling type 4 is not read as a reranker's (the agent's constant moved)",
        U,
        GGUF_CONTEXT,
        "POOLING_RANK = 4\n",
        "POOLING_RANK = 5\n",
    ),
    (
        "attention that is not causal is not an embedder",
        U,
        RUN_MODE,
        "    if facts.causal is False:\n",
        "    if False:\n",
    ),
    (
        "a pooling type other than rank is not an embedder",
        ("agent-unit", "acc-core"),
        RUN_MODE,
        "    if facts.pooling_type is not None:\n        return Resolved(\n",
        "    if False:\n        return Resolved(\n",
    ),
    # ---- auto against an explicit choice ----------------------------------------------------
    (
        "THE HEADER BEATS AN EXPLICIT CHAT",
        ("agent-unit", "acc-override"),
        RUN_MODE,
        '    if declared is RuntimeMode.chat:\n        return Resolved(Task.chat, "the runtime says chat")\n',
        '    if False:\n        return Resolved(Task.chat, "the runtime says chat")\n',
    ),
    (
        "an explicit embedding is not honoured for a file whose header says chat",
        ("agent-unit", "acc-override"),
        RUN_MODE,
        "    if declared is RuntimeMode.embedding:\n",
        "    if False:\n",
    ),
    (
        "an explicit reranking is not honoured",
        U,
        RUN_MODE,
        "    if declared is RuntimeMode.reranking:\n",
        "    if False:\n",
    ),
    (
        "the profile's mode is dropped on its way to the runtime",
        U,
        RUN_WORKER,
        '            "mode": profile.get("mode") or "auto",\n',
        '            "mode": "auto",\n',
    ),
    (
        "a run adopts a runtime declared under another mode",
        U,
        RUN_WORKER,
        'for key in ("engine", "modelPath", "mode", "flags", "extraArgs", "env"):',
        'for key in ("engine", "modelPath", "flags", "extraArgs", "env"):',
    ),
    (
        "a runtime that says no mode is a different declaration from one that says auto",
        U,
        RUN_WORKER,
        '    return (value or RuntimeMode.auto) if key == "mode" else value\n',
        "    return value\n",
    ),
    # ---- no idle unload for a search model --------------------------------------------------
    (
        "THE EMBEDDER KEEPS THE IDLE TIMEOUT IT WAS DECLARED WITH",
        ("agent-unit", "acc-idle"),
        RUNTIMES,
        "            idleUnloadSeconds=None if searching else spec.idleUnloadSeconds,\n",
        "            idleUnloadSeconds=spec.idleUnloadSeconds,\n",
    ),
    (
        "an embedder is started on demand",
        U,
        RUNTIMES,
        "            startOnDemand=None if searching else spec.startOnDemand,\n",
        "            startOnDemand=spec.startOnDemand,\n",
    ),
    (
        "what a runtime was started as is never read off its command line",
        ("agent-unit", "acc-idle"),
        RUNTIMES,
        "        searching = started is not None and any(started)\n",
        "        searching = False\n",
    ),
    (
        "a running embedder is offered to admission for eviction",
        U,
        ROUTES,
        '            spec=other.model_copy(update={"idleUnloadSeconds": view.idleUnloadSeconds}),\n',
        "            spec=other,\n",
    ),
    (
        "capabilities never say a runtime embeds or reranks",
        ("agent-unit", "acc-core"),
        RUNTIMES,
        '                    update={"embeddings": embeds, "reranking": reranks}\n',
        "                    update={}\n",
    ),
    (
        "a reranker is reported as an embedder too",
        U,
        RUN_MODE,
        "    return embedding and not reranking, reranking\n",
        "    return embedding, reranking\n",
    ),
    # ---- the Library's rerank capability, from header bytes ---------------------------------
    (
        "THE LIBRARY NEVER SAYS RERANK",
        ("library-unit", "acc-core"),
        LIB_GGUF,
        '        if self.arch_key("pooling_type") == POOLING_RANK:\n            return True\n',
        '        return False\n        if self.arch_key("pooling_type") == POOLING_RANK:\n            return True\n',
    ),
    (
        "rank pooling is read as the wrong number",
        ("library-unit",),
        LIB_GGUF,
        "POOLING_RANK = 4\n",
        "POOLING_RANK = 3\n",
    ),
    (
        "classifier labels are not a reranker",
        ("library-unit",),
        LIB_GGUF,
        "        if isinstance(labels, list):\n            return len(labels) > 0\n",
        "        if isinstance(labels, list):\n            return False\n",
    ),
    (
        "a reranker is also listed as an embedding model",
        ("library-unit", "acc-core"),
        LIB_SCANNER,
        "                embedding=metadata.is_search_embedding,\n",
        "                embedding=metadata.is_embedding,\n",
    ),
    (
        "the scanner does not say rerank",
        ("library-unit", "acc-core"),
        LIB_SCANNER,
        "                rerank=metadata.is_rerank,\n",
        "",
    ),
    (
        "preflight does not say rerank",
        ("library-unit",),
        LIB_PREFLIGHT,
        "                rerank=meta.is_rerank,\n",
        "",
    ),
    (
        "a reranker the header can name by labels alone is listed as chat",
        ("library-unit",),
        LIB_SCANNER,
        "                chat=not (metadata.is_embedding or metadata.is_rerank),\n",
        "                chat=not metadata.is_embedding,\n",
    ),
    # ---- the chat-argv regression test -------------------------------------------------------
    (
        "THE REGRESSION: a chat header with nothing to say resolves to an embedder",
        ("agent-chat-argv", "acc-core"),
        RUN_MODE,
        CHAT_FALLTHROUGH,
        CHAT_FALLTHROUGH.replace("Task.chat", "Task.embedding"),
    ),
    (
        "a header that cannot be read resolves to an embedder",
        ("agent-chat-argv",),
        RUN_MODE,
        CHAT_UNREADABLE,
        CHAT_UNREADABLE.replace("Task.chat", "Task.embedding"),
    ),
    (
        "a chat model is given a search model's four defaults",
        ("agent-chat-argv", "acc-core"),
        LLAMA,
        SEARCH_DEFAULTS_IF,
        SEARCH_DEFAULTS_IF.replace("if launch.search:", "if True:"),
    ),
    (
        "every chat model's command line gets one flag more, whatever the mode",
        ("agent-chat-argv",),
        LLAMA,
        '        argv += ["--alias", alias]\n',
        '        argv += ["--alias", alias, "--no-warmup"]\n',
    ),
    # ---- the driver, and the companion that keeps it in step --------------------------------
    (
        "THE DRIVER RACE: a 503 while the model loads is recorded as 'does not embed'",
        ("driver-unit",),
        DRIVER,
        "            if status in _NOT_NOW:\n",
        "            if False:\n",
    ),
    (
        "THE CRASH: the driver asks a reranker to embed (the rerank question is never asked first)",
        ("driver-unit", "acc-rerank"),
        DRIVER,
        "        reranks = await self.probe_rerank()\n",
        "        reranks = False\n",
    ),
    (
        "a backend that cannot say yet whether it reranks is asked to embed all the same",
        ("driver-unit",),
        DRIVER,
        "        if reranks is None:\n"
        "            # Not known yet, and the next question is not safe to ask until it is.\n"
        "            return False\n",
        "",
    ),
    (
        "a backend that is still loading is recorded as one that does not rerank",
        ("driver-unit",),
        DRIVER,
        "        if response.status_code in _NOT_NOW:\n",
        "        if False:\n",
    ),
    (
        "a refusal to rerank is not kept: the question is asked again at every poll",
        ("driver-unit",),
        DRIVER,
        "        self._rerank = answer\n        return answer\n",
        "        return answer\n",
    ),
    (
        "a runtime edited to start as something else keeps the driver that learned the old answer",
        ("agent-unit", "acc-flip"),
        ROUTES,
        COMPANION_ASKS,
        "            and False\n",
    ),
    (
        "every edit restarts the driver, whether or not what the runtime starts as changed",
        U,
        ROUTES,
        COMPANION_ASKS,
        "            and True\n",
    ),
]


def run_gate(name: str) -> tuple[int, str, str]:
    """`(exit code, why it failed, the tail of its output)`."""
    where, command = GATES[name]
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    try:
        done = subprocess.run(
            command,
            cwd=str(ROOT / where),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)", ""
    out = (done.stdout or "") + (done.stderr or "")
    lines = out.splitlines()
    first = [ln.strip()[:230] for ln in lines if ln.startswith(("FAILED ", "FAIL ", "ERROR "))][:2]
    why = " | ".join(first) or (lines[-1][:230] if lines else "")
    return done.returncode, why, out[-1800:]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", action="append", choices=sorted(GATES))
    parser.add_argument("--label", action="append", help="run only entries whose label has this")
    parser.add_argument("--anchors", action="store_true", help="check every anchor, run nothing")
    args = parser.parse_args()
    chosen = [
        (label, [g for g in gates if not args.gate or g in args.gate], relative, old, new)
        for label, gates, relative, old, new in SABOTAGES
        if not args.label or any(part in label for part in args.label)
    ]
    chosen = [entry for entry in chosen if entry[1]]
    gates_used = sorted({g for _label, gates, *_rest in chosen for g in gates})

    missing = []
    for label, _gates, relative, old, _new in chosen:
        count = io.open(ROOT / relative, encoding="utf-8").read().count(old)
        if count != 1:
            missing.append((label, count))
    if missing:
        for label, count in missing:
            print(f"[ANCHOR ] {label}: matched {count} times")
        return 1
    if args.anchors:
        print(f"{len(chosen)} anchors, each matched once")
        return 0

    backup = Path(tempfile.mkdtemp(prefix="mr3-sabotage-"))
    touched = sorted({relative for _label, _gates, relative, _old, _new in chosen})
    for relative in touched:
        destination = backup / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    print(f"copy in {backup}\n")

    for gate in gates_used:
        code, why, out = run_gate(gate)
        print(f"[baseline] {gate}: {'PASS' if code == 0 else 'FAIL'}", flush=True)
        if code != 0:
            print(out)
            return 1
    print()

    caught = escaped = runs = 0
    for label, gates, relative, old, new in chosen:
        path = ROOT / relative
        source = io.open(path, encoding="utf-8").read()
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            for gate in gates:
                runs += 1
                code, why, _out = run_gate(gate)
                if code != 0:
                    print(f"[caught ] ({gate}) {label}\n          {why}", flush=True)
                    caught += 1
                else:
                    print(f"[ESCAPED] ({gate}) {label}", flush=True)
                    escaped += 1
        finally:
            shutil.copy2(backup / relative, path)  # restore FROM THE COPY
    print(f"\n{caught} caught, {escaped} escaped, {runs} sabotage runs over {len(chosen)} breaks")

    drift = [relative for relative in touched if digest(ROOT / relative) != digest(backup / relative)]
    print(f"[restored] {len(touched)} files compared with the copy byte for byte: "
          f"{'all identical' if not drift else 'DIFFER: ' + ', '.join(drift)}", flush=True)
    if drift:
        return 1
    for gate in [g for g in gates_used if not g.startswith("acc-") or g == "acc-core"]:
        code, why, out = run_gate(gate)
        print(f"[restored] {gate}: {'PASS' if code == 0 else 'FAIL'}", flush=True)
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
