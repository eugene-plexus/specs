"""Sabotage pass for P8: web search run by this install, and P8e's image_generation.

Each sabotage puts back one way P8 could be wrong -- in the gateway, the
tool-driver, the agent or the control root -- runs the gate that should see
it, and requires that gate to FAIL. The acceptance runs the editable
installs, so a source edit is what runs; a unit gate runs that repo's own
suite in its own venv.

Restores are from byte copies taken before the first edit, never `git
checkout --`. It opens with a baseline assertion that every gate it uses
passes unsabotaged, and refuses to start if any anchor is not found exactly
once.

    python scripts/p8-sabotage.py <python with every component> [label filter]

The acceptance's SDK half needs `openai` and `anthropic` in that python or
`$EP_SDK_PYTHON`.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SPECS = Path(__file__).resolve().parents[1]
ROOT = SPECS.parent
GATEWAY = ROOT / "gateway" / "src" / "eugene_plexus_gateway"
TOOLS = ROOT / "tool-driver" / "src" / "eugene_plexus_tool_driver"
AGENT = ROOT / "agent" / "src" / "eugene_plexus_agent"
CONTROL = ROOT / "control" / "src" / "eugene_plexus_control"
ACCEPTANCE = SPECS / "scripts" / "p8-search-acceptance.py"

SERVER_TOOLS = GATEWAY / "server_tools.py"
ANTHROPIC = GATEWAY / "anthropic.py"
RESPONSES = GATEWAY / "responses.py"
ROUTE = GATEWAY / "routes" / "inference.py"
ADMISSION = GATEWAY / "admission.py"
ROUTING = GATEWAY / "routing.py"


def venv(repo: str) -> str:
    return str(ROOT / repo / ".venv" / "Scripts" / "python.exe")


#: gate name -> (command, working directory)
GATES = {
    "acceptance": None,  # filled in from argv: the python holding every component
    "gateway": ([venv("gateway"), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
                 "tests/test_server_tools.py", "tests/test_image_tool.py", "tests/test_routing.py"],
                ROOT / "gateway"),
    "tools": ([venv("tool-driver"), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"],
              ROOT / "tool-driver"),
    "control": ([venv("control"), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
                 "tests/test_topology.py"], ROOT / "control"),
    "agent": ([venv("agent"), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
               "tests/test_client_admission.py"], ROOT / "agent"),
}


@dataclass(frozen=True)
class Sabotage:
    label: str
    edits: tuple[tuple[Path, str, str], ...]
    gate: str = "acceptance"
    #: Why it is expected to ESCAPE, when it is: another layer does the job.
    escapes: str | None = None


SABOTAGES: list[Sabotage] = [
    # --- the gateway: whether a search may run --------------------------------------
    Sabotage("a local-only key searches",
             ((SERVER_TOOLS, '    if context is not None and getattr(context, "local_only", False):\n',
               "    if False:\n"),)),
    Sabotage("a key's tool scope is ignored",
             ((SERVER_TOOLS, "    if not permits(allowed, WEB_SEARCH):\n", "    if False:\n"),)),
    Sabotage("the key's allowedTools is never read off its admission",
             ((ADMISSION, "        return list(tools) if isinstance(tools, list) else None\n",
               "        return None\n"),)),
    Sabotage("Codex's external_web_access false searches anyway",
             ((RESPONSES, '        if searches[0].get("external_web_access") is False:\n', "        if False:\n"),)),
    Sabotage("Claude Code's web search tool is refused again",
             ((ANTHROPIC, "        if server_side and server_tools.ANTHROPIC_TOOL.match(str(server_side)):\n",
               "        if False:\n"),)),
    Sabotage("only one Anthropic tool date is accepted",
             ((SERVER_TOOLS, 'ANTHROPIC_TOOL = re.compile(r"^web_search_\\d{8}$")\n',
               'ANTHROPIC_TOOL = re.compile(r"^web_search_20250305$")\n'),), gate="gateway"),
    # --- the gateway: where it runs ---------------------------------------------------
    Sabotage("a backend that searches itself is searched for too",
             ((SERVER_TOOLS, '            if "webSearchOptions" in settings:\n', "            if False:\n"),)),
    Sabotage("search accounts are never discovered",
             ((ROUTING, '                (tools if entry.get("kind") == "tool-driver" else out).append(\n',
               "                out.append(\n"),)),
    Sabotage("a paid account is tried before a free one",
             ((ROUTING, '                a.info.billing != "free",\n', ""),)),
    # --- the gateway: the loop --------------------------------------------------------
    Sabotage("the first turn is not made to search when search is the only tool",
             ((SERVER_TOOLS, "            choice = ToolChoice.required\n", "            pass\n"),)),
    Sabotage("the model is not told to cite",
             ((SERVER_TOOLS, '    lines.append("Cite the pages you use as markdown links, like [title](address).")\n',
               ""),)),
    Sabotage("the answer's citations are not returned",
             ((SERVER_TOOLS, "            annotations += [\n", "            annotations + [\n"),)),
    Sabotage("a second account is never tried",
             ((SERVER_TOOLS, "                if not exc.worth_another_account:\n", "                if True:\n"),)),
    Sabotage("a failed search fails the request",
             ((SERVER_TOOLS, "            await self.runner.run(execution)\n",
               "            await self.runner.run(execution)\n"
               '            if execution.outcome == "error":\n'
               "                raise RuntimeError(execution.error)\n"),)),
    Sabotage("the limit is not enforced",
             ((SERVER_TOOLS,
               '        if sum(1 for e in self.executions if e.outcome != "over_limit") >= self.limit:\n',
               "        if False:\n"),), gate="gateway"),
    Sabotage("failover is not pinned after the first search",
             ((SERVER_TOOLS, "            if pin is not None:\n", "            if False:\n"),), gate="gateway"),
    Sabotage("a streamed search call reaches the caller",
             ((SERVER_TOOLS, "                    if names.get(index) == self._tool_name:\n",
               "                    if False:\n"),), gate="gateway"),
    Sabotage("a profile default throws away the loop's turns",
             ((ROUTE, "            return original.model_copy(\n", "            return filled.model_copy(\n"),),
             gate="gateway"),
    # --- the gateway: each door's record ---------------------------------------------
    Sabotage("a web_search_call item carries no sources",
             ((RESPONSES, '                {"type": "url", "url": r.get("url")}\n                for r in execution.results\n',
               '                {"type": "url", "url": r.get("url")}\n                for r in []\n'),)),
    Sabotage("the Responses stream never says searching",
             ((RESPONSES, '                "response.web_search_call.searching",\n', ""),)),
    Sabotage("Anthropic's usage does not count the searches",
             ((ANTHROPIC, "    if web_searches:\n", "    if False:\n"),)),
    Sabotage("the searches are not recorded",
             ((ROUTE, "                    for e in (searched.executions if searched is not None else [])\n",
               "                    for e in []\n"),)),
    Sabotage("a loop's turns are counted as a cascade",
             ((ROUTE, "        extra_turns = max(0, searched.turns - 1) if searched is not None else 0\n",
               "        extra_turns = 0\n"),)),
    # --- the tool-driver ------------------------------------------------------------
    Sabotage("SearXNG's JSON-off 403 is not named",
             ((TOOLS / "providers.py", "    if response.status_code == 403:\n", "    if False:\n"),)),
    Sabotage("a result outside the allowed domains reaches the model",
             ((TOOLS / "service.py", "        hits = keep(found.hits, query.allowed, query.blocked)[:max_results]\n",
               "        hits = found.hits[:max_results]\n"),), gate="tools"),
    Sabotage("a Brave key is written in plaintext",
             ((TOOLS / "config.py", "                and self._master_key is not None\n", "                and False\n"),)),
    Sabotage("an account that is not set up offers web_search",
             ((TOOLS / "routes" / "info.py", "        tools=[ToolName.web_search] if configured else [],\n",
               "        tools=[ToolName.web_search],\n"),), gate="tools"),
    # --- the agent -------------------------------------------------------------------
    Sabotage("the agent hands a tool-driver no master key",
             ((AGENT / "supervisor.py", '                kind_value in {"library", "inference-driver", "tool-driver"}\n',
               '                kind_value in {"library", "inference-driver"}\n'),)),
    Sabotage("the proxy cannot reach a search account by name",
             ((AGENT / "routes" / "proxy.py", '_NAMED_KINDS = frozenset({"inference-driver", "tool-driver"})\n',
               '_NAMED_KINDS = frozenset({"inference-driver"})\n'),)),
    # The acceptance's agent is enrolled, and an enrolled agent forwards a
    # key's admission to the control root, so the CONTROL root's copy is the
    # one this run exercises. The agent's copy decides only on a standalone
    # install and its own unit test is the check for it (measured
    # 2026-09-29: the agent sabotage escaped the acceptance, as P1's matcher
    # did on 2026-09-27).
    Sabotage("the control root drops a key's allowedTools",
             ((CONTROL / "client_admission.py", '        **({"allowedTools": tools} if tools is not None else {}),\n',
               ""),)),
    Sabotage("the agent drops a key's allowedTools",
             ((AGENT / "client_admission.py", '        **({"allowedTools": tools} if tools is not None else {}),\n',
               ""),), gate="agent"),
    # --- P8e: image_generation on /v1/responses ------------------------------------
    Sabotage("the model is handed the image's bytes",
             ((SERVER_TOOLS, '        "do not describe details you cannot see."\n',
               '        "do not describe details you cannot see." + str(execution.image)\n'),)),
    Sabotage("the image item carries no result",
             ((RESPONSES, '        "result": execution.image if made else None,\n',
               '        "result": None,\n'),), gate="gateway"),
    Sabotage("the image stream never says generating",
             ((RESPONSES, '                "response.image_generation_call.generating",\n', ""),),
             gate="gateway"),
    Sabotage("an image tool that cannot run is removed silently",
             ((RESPONSES, '        if kind == "image_generation" and images is not None:\n',
               '        if kind == "image_generation":\n            continue\n'
               '        if kind == "image_generation" and images is not None:\n'),), gate="gateway"),
    Sabotage("the gateway's image model setting is never read",
             ((ROUTE, '            settings.get("imageToolModel") if settings is not None else None,\n',
               "            None,\n"),), gate="gateway"),
    Sabotage("the tool's own image model is ignored",
             ((SERVER_TOOLS, "    if plan.model and _serves_images(table, plan.model, allowed, local_only):\n",
               "    if False:\n"),), gate="gateway"),
    Sabotage("a key's tool scope does not reach image_generation",
             ((SERVER_TOOLS, "    if not permits(allowed_tools, IMAGE_GENERATION):\n", "    if False:\n"),)),
    Sabotage("searches and images do not share one budget",
             ((SERVER_TOOLS, "        return len(searches) + len(images)\n", "        return len(images)\n"),),
             gate="gateway"),
    Sabotage("the image backend's attempts count as the request's",
             ((SERVER_TOOLS, "                del rows[before:]\n", "                pass\n"),), gate="gateway"),
    Sabotage("a failed image fails the request",
             ((SERVER_TOOLS, "        except DriverError as exc:\n", "        except ZeroDivisionError as exc:\n"),),
             gate="gateway"),
    Sabotage("a handed-back image is sent to the model as bytes",
             ((RESPONSES, '        self._parts.append(TextContentPart(type="text", text=note))\n',
               '        self._parts.append(TextContentPart(type="text", text=note + str(item.get("result"))))\n'),),
             gate="gateway"),
    Sabotage("images are not recorded",
             ((ROUTE, '        elif kind == "image":\n', "        elif False:\n"),)),
    Sabotage("the model's size overrides the caller's",
             ((SERVER_TOOLS, "            size=self.plan.size or execution.size,\n",
               "            size=execution.size or self.plan.size,\n"),), gate="gateway"),
    # --- the control root -----------------------------------------------------------
    Sabotage("an unknown kind fails the whole union view",
             ((CONTROL / "routes" / "topology.py", "    try:\n        return ComponentPlacement.model_validate(values)\n"
               "    except ValidationError:\n",
               "    try:\n        return ComponentPlacement.model_validate(values)\n"
               "    except KeyError:\n"),), gate="control"),
]


def run_gate(gate: str, python: str) -> int:
    if gate == "acceptance":
        command, cwd = [python, str(ACCEPTANCE)], SPECS
    else:
        command, cwd = GATES[gate]  # type: ignore[misc]
    # UTF-8 and replace: a gate's own messages carry non-ASCII (a middle
    # dot, a curly quote), and the locale code page crashed the reader
    # thread on the first one, eleven sabotages in.
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=900,
                            stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    lines = (result.stdout + result.stderr).strip().splitlines()
    print(f"    [{gate}] exit={result.returncode}  {lines[-1] if lines else ''}", flush=True)
    return result.returncode


def main() -> None:
    python = sys.argv[1] if len(sys.argv) > 1 else sys.executable
    only = sys.argv[2] if len(sys.argv) > 2 else None
    if only and only.startswith("--from="):
        # Resume a pass that stopped: every sabotage from this 1-based one on.
        chosen = SABOTAGES[int(only.split("=", 1)[1]) - 1 :]
    else:
        chosen = [s for s in SABOTAGES if only is None or only in s.label]
    files = {path for s in chosen for path, _, _ in s.edits}
    copies = {path: path.read_bytes() for path in files}
    for sabotage in chosen:
        for path, old, _ in sabotage.edits:
            if copies[path].decode("utf-8").replace("\r\n", "\n").count(old) != 1:
                raise SystemExit(f"sabotage anchor not found exactly once in {path.name}: {sabotage.label}")
    caught = 0
    escaped: list[str] = []
    expected: list[str] = []
    try:
        for gate in sorted({s.gate for s in chosen}):
            print(f"baseline: {gate} must pass unsabotaged", flush=True)
            if run_gate(gate, python) != 0:
                raise SystemExit(f"BASELINE FAILED: {gate} does not pass unsabotaged")
        print("baselines PASS\n", flush=True)
        for sabotage in chosen:
            print(f"sabotage: {sabotage.label}", flush=True)
            sources: dict[Path, str] = {}
            for path, old, new in sabotage.edits:
                source = sources.get(path, copies[path].decode("utf-8").replace("\r\n", "\n"))
                sources[path] = source.replace(old, new)
            for path, source in sources.items():
                path.write_text(source, encoding="utf-8", newline="\n")
            try:
                code = run_gate(sabotage.gate, python)
            finally:
                for path in sources:
                    path.write_bytes(copies[path])
            if code != 0:
                caught += 1
                print("    CAUGHT", flush=True)
            elif sabotage.escapes:
                expected.append(sabotage.label)
                print(f"    escaped, as expected: {sabotage.escapes}", flush=True)
            else:
                escaped.append(sabotage.label)
                print("    ESCAPED", flush=True)
    finally:
        for path, data in copies.items():
            path.write_bytes(data)
    print(f"\n{caught} of {len(chosen)} caught; {len(expected)} expected escapes; "
          f"{len(escaped)} unexpected escapes", flush=True)
    for label in escaped:
        print(f"  ESCAPED: {label}", flush=True)
    raise SystemExit(1 if escaped else 0)


if __name__ == "__main__":
    main()
