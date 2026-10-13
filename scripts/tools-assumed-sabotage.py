"""Sabotage pass for "tools are assumed": the pair acceptance must be able to fail.

Each sabotage puts back one way the gateway and the inference-driver could be wrong
(the ones `docs/design/tools-assumed.md` says went wrong, or came near it), runs the
part of `tools-assumed-acceptance.py` that should see it, and requires that part to
FAIL, on the check it is for, **and for the reason the sabotage is** (each names a
regex that one of the problems the check lists must match: a gate that failed for
another cause would be luck, not a catch).

**No checkout is touched.** The gateway and the driver at the pins are checked out
beside this repository (`../gateway`, `../inference-driver`), and a sabotage is an
edit to a copy of their packages in a temporary tree, which the acceptance is told
to run instead of the installed ones (`EP_GATEWAY_SRC`, `EP_DRIVER_SRC`). The copies
are restored from byte copies after every sabotage, never with `git checkout --`.
The pass opens with a baseline (every gate it uses must pass on the unedited
copies, and must say that it ran them), refuses to start if an anchor is not found
exactly once, and ends by showing that the two checkouts hold the bytes they held
when it began, and that git sees no change in either.

    python scripts/tools-assumed-sabotage.py <python with the gateway and the driver> [label filter | --from=N]
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

SPECS = Path(__file__).resolve().parents[1]
ROOT = SPECS.parent
ACCEPTANCE = SPECS / "scripts" / "tools-assumed-acceptance.py"
PACKAGES = {
    "gateway": ROOT / "gateway" / "src" / "eugene_plexus_gateway",
    "driver": ROOT / "inference-driver" / "src" / "eugene_plexus_inference_driver",
}
REPOS = [ROOT / "gateway", ROOT / "inference-driver"]

#: gate name -> (arguments to the acceptance, the check it must fail, as the acceptance numbers it)
GATES: dict[str, tuple[list[str], str]] = {
    "header (Nova)": (["--only", "header", "--families", "or-nova,local"], "1"),
    "header (Nova and OpenRouter's other gaps)": (
        ["--only", "header", "--families", "or-nova,or-nopar,local"],
        "1",
    ),
    "header (the CLI)": (["--only", "header", "--families", "claude-cli,local"], "1"),
    "slots (the CLI)": (["--only", "slots", "--families", "claude-cli"], "2"),
    "counts": (["--only", "counts"], "3"),
    "failover": (["--only", "failover"], "1b"),
    "heads": (["--only", "heads"], "4"),
}

GATEWAY_ROUTE = "routes/inference.py"
DRIVER_OPENAI = "engines/openai_compat_http.py"

#: `(tree, file, old, new)`: `old` must be in the file exactly once.
Edit = tuple[str, str, str, str]

#: Holds a stream's head until its backend has spoken: the answer is begun before the response is
#: made, so the head cannot go out until the first frame has come.
HOLD = (
    "        _first = await _held.__anext__()\n"
    "\n"
    "        async def _chained() -> AsyncIterator[str]:\n"
    "            yield _first\n"
    "            async for _chunk in _held:\n"
    "                yield _chunk\n"
    "\n"
)


@dataclass(frozen=True)
class Sabotage:
    label: str
    edits: tuple[Edit, ...]
    gate: str
    #: A regex that a problem the gate reports must match: that it fails is not enough, it must
    #: fail for the reason the sabotage is (a gate that failed for another cause would be luck).
    because: str = ""


SABOTAGES: list[Sabotage] = [
    # --- the none rule, in the gateway and in the driver ---------------------------------
    Sabotage(
        "the gateway's none rule is round four's (any toolChoice gap means no tools are sent)",
        (
            (
                "gateway",
                "ignored_settings.py",
                '    tools_unsent = sent(request, "toolChoice") == "none" and any(\n'
                '        entry.setting == "toolChoice" and "none" not in entry.values for entry in entries\n'
                "    )\n",
                '    tools_unsent = any(entry.setting == "toolChoice" for entry in entries) and (\n'
                '        sent(request, "toolChoice") == "none"\n'
                "    )\n",
            ),
        ),
        "header (Nova)",
        because=r"the gateway names \['tool_choice'\], its driver names \['parallel_tool_calls', 'tool_choice'\]",
    ),
    Sabotage(
        "a driver strips the tools for none on the Nova shape (a gap that names none is read as one that does not)",
        (
            (
                "driver",
                DRIVER_OPENAI,
                "        return any(\n"
                '            gap.setting == "toolChoice" and ToolChoice.none.value not in gap.values\n'
                "            for gap in self._gaps_for(target)\n"
                "        )\n",
                '        return any(gap.setting == "toolChoice" for gap in self._gaps_for(target))\n',
            ),
        ),
        "header (Nova)",
        because=r"the gateway names \['tool_choice'\], its driver names \[\]",
    ),
    Sabotage(
        "an OpenRouter gap is named and delivered all the same",
        (
            (
                "driver",
                DRIVER_OPENAI,
                "        return frozenset(gap.setting for gap in self._gaps_for(target))\n",
                "        return frozenset()\n",
            ),
        ),
        "header (Nova and OpenRouter's other gaps)",
        because=r"the provider was sent .* the design says",
    ),
    # --- a whole answer is named by who served it ----------------------------------------
    Sabotage(
        "the gateway reads the header before the call for a whole answer (the backend asked first, not the one that served)",
        (
            (
                "gateway",
                GATEWAY_ROUTE,
                '        answered = getattr(self.client, "served_candidate", None)\n'
                "        if answered is None:\n"
                "            return self.not_honoured\n"
                '        return _not_honoured_by(getattr(self.client, "entries", {}).get(answered), self.generate)\n',
                "        return self.not_honoured\n",
            ),
        ),
        "failover",
        because=r"a whole answer is named",
    ),
    # --- slots: the driver refuses what the gateway admitted -------------------------------
    Sabotage(
        "a CLI driver refuses tool_choice and parallel_tool_calls on a request that carries no tools (round four's cost)",
        (
            (
                "driver",
                "engines/base.py",
                "        unsupported -= set(TOOL_COMPANION_SETTINGS)\n",
                "        pass\n",
            ),
        ),
        "slots (the CLI)",
        because=r"not served, though the local model serves it alone: 400 .*cannot honor",
    ),
    # Admission turns a model whose tools are off away twice: by what its driver reports of
    # them, and by its list of settings, which does not name `tools`. A slot still serves
    # with the first gone (measured: that sabotage escaped `slots`), so what the first
    # alone makes is the wording of the refusal, which is the driver's report.
    Sabotage(
        "admission stops saying that the driver reports tools cannot be carried (a refusal that blames the request)",
        (
            (
                "gateway",
                "admission.py",
                "            if tools and not carries:\n"
                "                told_no_tools += 1\n"
                "                return None\n",
                "            if False:\n"
                "                told_no_tools += 1\n"
                "                return None\n",
            ),
        ),
        "header (the CLI)",
        because=r"does not say that its driver reports",
    ),
    # --- the counts -------------------------------------------------------------------------
    Sabotage(
        "the count door lets a 503 through (a key or a listing that cannot be checked)",
        (
            (
                "gateway",
                GATEWAY_ROUTE,
                "        if failure.status < 500:\n"
                "            raise\n"
                "        return _Count(reason=failure.message)\n",
                "        if failure.status < 500 or failure.status == 503:\n"
                "            raise\n"
                "        return _Count(reason=failure.message)\n",
            ),
        ),
        "counts",
        because=r"HTTP 503",
    ),
    Sabotage(
        "the Messages count lets an unreadable key policy through as a 5xx",
        (
            (
                "gateway",
                GATEWAY_ROUTE,
                "        if refusal.status >= 500:\n"
                "            # The key policy cannot be read: a count that cannot be given, and not a 503\n",
                "        if False:\n"
                "            # The key policy cannot be read: a count that cannot be given, and not a 503\n",
            ),
        ),
        "counts",
        because=r"policy 500 key messages .*HTTP 503",
    ),
    Sabotage(
        "the Responses count lets an unreadable key policy through as a 5xx",
        (
            (
                "gateway",
                GATEWAY_ROUTE,
                "        if refusal.status >= 500:\n"
                "            # The key policy cannot be read: a count that cannot be given, as on the\n",
                "        if False:\n"
                "            # The key policy cannot be read: a count that cannot be given, as on the\n",
            ),
        ),
        "counts",
        because=r"policy 500 key responses .*HTTP 503",
    ),
    # --- a stream's head -----------------------------------------------------------------------
    Sabotage(
        "the chat door's stream head names nothing of what the backend asked first ignores",
        (
            (
                "gateway",
                GATEWAY_ROUTE,
                '            headers=ignored_settings.added_to({}, prepared.not_honoured, "chat"),\n',
                '            headers=ignored_settings.added_to({}, (), "chat"),\n',
            ),
        ),
        "heads",
        because=r"the head names \[\]",
    ),
    Sabotage(
        "the chat door holds a stream's head until the backend's first frame",
        (
            (
                "gateway",
                GATEWAY_ROUTE,
                "        return StreamingResponse(\n"
                "            _stream_completion(\n"
                "                body, generate, client, table, started, rec=rec, output_cap=prepared.output_cap\n"
                "            ),\n"
                '            media_type="text/event-stream",\n',
                "        _held = _stream_completion(\n"
                "            body, generate, client, table, started, rec=rec, output_cap=prepared.output_cap\n"
                "        )\n" + HOLD + "        return StreamingResponse(\n"
                "            _chained(),\n"
                '            media_type="text/event-stream",\n',
            ),
        ),
        "heads",
        because=r"chat stream: no head came",
    ),
    Sabotage(
        "the Messages door holds a stream's head until the backend's first frame",
        (
            (
                "gateway",
                GATEWAY_ROUTE,
                "        return StreamingResponse(\n"
                "            _stream_anthropic(\n"
                "                body, prepared, model=body.model, display=anthropic.thinking_display(raw)\n"
                "            ),\n"
                '            media_type="text/event-stream",\n',
                "        _held = _stream_anthropic(\n"
                "            body, prepared, model=body.model, display=anthropic.thinking_display(raw)\n"
                "        )\n" + HOLD + "        return StreamingResponse(\n"
                "            _chained(),\n"
                '            media_type="text/event-stream",\n',
            ),
        ),
        "heads",
        because=r"messages stream: no head came",
    ),
    Sabotage(
        "the Responses stream opens with nothing until the backend speaks (no response.created)",
        (
            (
                "gateway",
                GATEWAY_ROUTE,
                "    for chunk in translator.start():\n        yield chunk\n",
                "    for chunk in ():\n        yield chunk\n",
            ),
        ),
        "heads",
        because=r"responses stream: the head came, then nothing",
    ),
    Sabotage(
        "the Responses door holds a stream's head until the backend's first frame",
        (
            (
                "gateway",
                GATEWAY_ROUTE,
                "    for chunk in translator.start():\n        yield chunk\n",
                "    for chunk in ():\n        yield chunk\n",
            ),
            (
                "gateway",
                GATEWAY_ROUTE,
                "        return StreamingResponse(\n"
                "            _stream_responses(body, prepared, translated, response_id, store),\n"
                '            media_type="text/event-stream",\n',
                "        _held = _stream_responses(body, prepared, translated, response_id, store)\n"
                + HOLD
                + "        return StreamingResponse(\n"
                "            _chained(),\n"
                '            media_type="text/event-stream",\n',
            ),
        ),
        "heads",
        because=r"responses stream: no head came",
    ),
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digests(package: Path) -> dict[str, str]:
    """Every file of a package (bytecode left out) and what it holds."""
    return {
        p.relative_to(package).as_posix(): digest(p)
        for p in sorted(package.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }


def git_status(repo: Path) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    return (done.stdout + done.stderr).strip()


def run_gate(python: str, gate: str, env: dict[str, str]) -> tuple[int, str]:
    """The acceptance, restricted to one gate: its exit status and what it said."""
    args, _label = GATES[gate]
    done = subprocess.run(
        # `--clean`: a gate that fails, as a sabotaged one must, leaves nothing behind
        [python, str(ACCEPTANCE), "--clean", *args],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=600,
        check=False,
    )
    return done.returncode, done.stdout + done.stderr


def verdict(output: str, label: str) -> tuple[str | None, list[str]]:
    """Whether the check `label` passed or failed in `output`, and the problems it listed."""
    status = re.search(rf"^(PASS|FAIL)\s+{re.escape(label)}\. ", output, re.M)
    problems: list[str] = []
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if re.match(rf"^FAIL\s+{re.escape(label)}\. ", line):
            for following in lines[index + 1 :]:
                found = re.match(r"^\s+- (.*)$", following)
                if found is None:
                    break
                problems.append(found.group(1))
    return (status.group(1) if status else None), problems


def main() -> None:
    python = sys.argv[1] if len(sys.argv) > 1 else sys.executable
    only = sys.argv[2] if len(sys.argv) > 2 else None
    if only and only.startswith("--from="):
        chosen = SABOTAGES[int(only.split("=", 1)[1]) - 1 :]
    else:
        chosen = [s for s in SABOTAGES if only is None or only in s.label]

    work = Path(tempfile.mkdtemp(prefix="tools-assumed-sabotage-"))
    before = {name: tree_digests(pkg) for name, pkg in PACKAGES.items()}
    status_before = {str(repo): git_status(repo) for repo in REPOS}
    print(
        f"the checkouts are not edited: a copy of each package is, in {work}",
        flush=True,
    )
    trees: dict[str, Path] = {}
    for name, package in PACKAGES.items():
        trees[name] = work / f"{name}-src"
        shutil.copytree(
            package,
            trees[name] / package.name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        if tree_digests(trees[name] / package.name) != before[name]:
            raise SystemExit(f"the copy of the {name} is not the {name}")

    env = {
        k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS")
    }
    env["EP_GATEWAY_SRC"] = str(trees["gateway"])
    env["EP_DRIVER_SRC"] = str(trees["driver"])
    env["PYTHONUTF8"] = "1"

    def path_of(tree: str, name: str) -> Path:
        return trees[tree] / PACKAGES[tree].name / name

    files = {path_of(tree, name) for s in chosen for tree, name, _, _ in s.edits}
    copies = {path: path.read_bytes() for path in files}
    for sabotage in chosen:
        for tree, name, old, _ in sabotage.edits:
            text = copies[path_of(tree, name)].decode("utf-8").replace("\r\n", "\n")
            if text.count(old) != 1:
                raise SystemExit(
                    f"sabotage anchor not found exactly once in {name}: {sabotage.label}"
                )

    caught = 0
    escaped: list[str] = []
    try:
        for gate in sorted({s.gate for s in chosen}):
            print(f"baseline: {gate} must pass, on the copies, unedited", flush=True)
            code, output = run_gate(python, gate, env)
            label = GATES[gate][1]
            seen, _ = verdict(output, label)
            ran = (
                f"gateway source: {trees['gateway']}" in output
                and f"driver source: {trees['driver']}" in output
            )
            lines = output.strip().splitlines()
            print(f"    exit={code}  {lines[-1] if lines else ''}", flush=True)
            if code != 0 or seen != "PASS":
                raise SystemExit(f"BASELINE FAILED: {gate}\n{output[-2000:]}")
            if not ran:
                raise SystemExit(
                    f"BASELINE FAILED: {gate} did not run the copies:\n{output[:600]}"
                )
        print("baselines PASS, on the copies\n", flush=True)
        for sabotage in chosen:
            print(f"sabotage: {sabotage.label}", flush=True)
            sources: dict[Path, str] = {}
            for tree, name, old, new in sabotage.edits:
                path = path_of(tree, name)
                text = sources.get(
                    path, copies[path].decode("utf-8").replace("\r\n", "\n")
                )
                sources[path] = text.replace(old, new)
            for path, text in sources.items():
                path.write_text(text, encoding="utf-8", newline="\n")
            try:
                code, output = run_gate(python, sabotage.gate, env)
            finally:
                for path in sources:
                    path.write_bytes(copies[path])
            label = GATES[sabotage.gate][1]
            seen, problems = verdict(output, label)
            lines = output.strip().splitlines()
            print(
                f"    [{sabotage.gate}] exit={code}  {lines[-1] if lines else ''}",
                flush=True,
            )
            reasons = [p for p in problems if re.search(sabotage.because, p)]
            if code == 1 and seen == "FAIL" and reasons:
                caught += 1
                print(f"    CAUGHT by check {label}: {reasons[0][:260]}", flush=True)
            else:
                escaped.append(sabotage.label)
                if code == 0:
                    why = "it passed"
                elif code == 1 and seen == "FAIL":
                    first = problems[0][:200] if problems else ""
                    why = f"check {label} failed, but not for this reason ({sabotage.because}): {first}"
                else:
                    why = f"exit {code}, and check {label} said {seen}"
                print(f"    ESCAPED ({why})", flush=True)
                if code not in (0, 1):
                    print(output[-1500:], flush=True)
    finally:
        for path, data in copies.items():
            path.write_bytes(data)
    after = {name: tree_digests(pkg) for name, pkg in PACKAGES.items()}
    untouched = (
        after == before and {str(r): git_status(r) for r in REPOS} == status_before
    )
    restored = all(
        tree_digests(trees[name] / PACKAGES[name].name) == before[name]
        for name in PACKAGES
    )
    print(
        f"\n{caught} of {len(chosen)} caught; {len(escaped)} unexpected escapes; "
        f"the copies restored: {restored}; the checkouts untouched (bytes and git status): {untouched}",
        flush=True,
    )
    for label in escaped:
        print(f"  ESCAPED: {label}", flush=True)
    shutil.rmtree(work, ignore_errors=True)
    raise SystemExit(1 if escaped or not untouched or not restored else 0)


if __name__ == "__main__":
    main()
