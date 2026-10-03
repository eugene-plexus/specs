"""Sabotage pass for cache-aware balancing v2 (CB1-CB5).

Each sabotage puts back one way a slice could be wrong -- in the driver, the
gateway or the agent -- runs the gate that should see it, and requires that
gate to FAIL. A gate is one repo's own tests in its own venv.

Restores are from byte copies taken before the first edit, never `git
checkout --`. It opens with a baseline assertion that every gate it uses
passes unsabotaged, and refuses to start if any anchor is not found exactly
once.

    python scripts/cb-sabotage.py [label filter | --from=N]
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SPECS = Path(__file__).resolve().parents[1]
ROOT = SPECS.parent
DRIVER = ROOT / "inference-driver" / "src" / "eugene_plexus_inference_driver"
GATEWAY = ROOT / "gateway" / "src" / "eugene_plexus_gateway"
AGENT = ROOT / "agent" / "src" / "eugene_plexus_agent"

FAILURES = DRIVER / "failures.py"
GENERATE = DRIVER / "routes" / "generate.py"
OPENAI = DRIVER / "engines" / "openai_compat_http.py"
CLIENT = GATEWAY / "driver_client.py"
BUDGET = GATEWAY / "budget.py"
ROUTING = GATEWAY / "routing.py"
CONFIG = GATEWAY / "config.py"
AFFINITY = GATEWAY / "affinity.py"
APP = GATEWAY / "app.py"
INFERENCE = GATEWAY / "routes" / "inference.py"
RESPONSES = GATEWAY / "responses.py"
ANTHROPIC = GATEWAY / "anthropic.py"
METRICS = GATEWAY / "metrics.py"
LLAMA = AGENT / "engines" / "llama_cpp.py"
RUNTIMES = AGENT / "runtimes.py"
SLOTS = DRIVER / "slots.py"
COMPANIONS = AGENT / "companions.py"


def venv(repo: str) -> str:
    return str(ROOT / repo / ".venv" / "Scripts" / "python.exe")


def pytest(repo: str, *tests: str) -> tuple[list[str], Path]:
    return [venv(repo), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests], ROOT / repo


#: gate name -> (command, working directory)
GATES = {
    "driver": pytest("inference-driver", "tests/test_pool_capacity.py",
                     "tests/test_failover_safety.py", "tests/test_slot_pinning.py"),
    "gateway": pytest("gateway", "tests/test_pool_budget.py", "tests/test_failover_safety.py",
                      "tests/test_routing.py", "tests/test_affinity.py",
                      "tests/test_load_balancing_setting.py", "tests/test_evictions.py",
                      "tests/test_prompt_cache_metrics.py", "tests/test_metrics.py",
                      "tests/test_responses.py", "tests/test_anthropic_messages.py"),
    "agent": pytest("agent", "tests/test_context_pool.py", "tests/test_runtime_end_to_end.py",
                    "tests/test_companions.py"),
}


@dataclass(frozen=True)
class Sabotage:
    label: str
    edits: tuple[tuple[Path, str, str], ...]
    gate: str
    #: Why it is expected to ESCAPE, when it is: another layer does the job.
    escapes: str | None = None


SABOTAGES: list[Sabotage] = [
    # --- CB3a: a full pool is capacity, in the driver --------------------------------
    Sabotage("the driver never recognises a full pool",
             ((FAILURES, "    return bool(_POOL_FULL.search(str(error)))\n", "    return False\n"),),
             "driver"),
    Sabotage("a full pool is not safe to cascade",
             ((FAILURES, '    if capacity_refused(error):\n        return "safe"\n', ""),),
             "driver"),
    Sabotage("a full pool is still a 502",
             ((GENERATE, "    if capacity_refused(e):\n", "    if False:\n"),),
             "driver"),
    Sabotage("a 4xx saying the same words becomes capacity",
             ((FAILURES, "    if isinstance(status, int) and status < 500:\n        return False\n", ""),),
             "driver"),
    Sabotage("the stream's error frame is dropped again",
             ((OPENAI, "                    if failure is not None:\n", "                    if False:\n"),),
             "driver"),
    Sabotage("an OpenRouter error riding on a choice becomes a failure",
             ((OPENAI, '    if not isinstance(event, dict) or "choices" in event:\n',
               "    if not isinstance(event, dict):\n"),),
             "driver"),
    # --- CB3a: the gateway's circuit -------------------------------------------------
    Sabotage("the circuit counts a full pool",
             ((CLIENT, "                and not capacity_refused(error),\n", ""),),
             "gateway"),
    Sabotage("the gateway never recognises the driver's capacity type",
             ((CLIENT, '        and str(exc.problem.type or "").endswith("#backend-capacity")\n',
               '        and str(exc.problem.type or "").endswith("#nothing")\n'),),
             "gateway"),
    # --- CB3c: the budget ------------------------------------------------------------
    Sabotage("no spare is kept",
             ((BUDGET, "        return held + tokens <= int(pool * (1 - SPARE))\n",
               "        return held + tokens <= pool\n"),),
             "gateway"),
    Sabotage("a turn alone on its runtime may not go",
             ((BUDGET, "        if held == 0 or prompt > pool:\n", "        if prompt > pool:\n"),),
             "gateway"),
    Sabotage("too big for the pool is judged with max_tokens",
             ((BUDGET, "        if held == 0 or prompt > pool:\n", "        if held == 0 or tokens > pool:\n"),),
             "gateway"),
    Sabotage("a held conversation takes any replica with room",
             ((BUDGET, "        waiting_on = ordered[:1] if self._held else ordered\n",
               "        waiting_on = ordered\n"),),
             "gateway"),
    Sabotage("a turn never waits",
             ((BUDGET, "            await self._ledger.changed(remaining)\n",
               "            return ordered\n"),),
             "gateway"),
    Sabotage("the wait has no bound",
             ((BUDGET, "            if remaining <= 0:\n", "            if False:\n"),),
             "gateway"),
    Sabotage("room is never given back",
             ((BUDGET, "            self._ledger.give(self._lease[1], self.tokens)\n",
               "            pass\n"),),
             "gateway"),
    Sabotage("max_tokens is not counted",
             ((BUDGET, "    return tokens, tokens + max(0, max_tokens or 0)\n",
               "    return tokens, tokens\n"),),
             "gateway"),
    Sabotage("a conversation's last prompt is never used",
             ((BUDGET, "    if seen is not None and chars >= seen.chars:\n", "    if False:\n"),),
             "gateway"),
    Sabotage("tools are not counted",
             ((BUDGET, '    for name in ("messages", "tools"):\n', '    for name in ("messages",):\n'),),
             "gateway"),
    Sabotage("the pool is not read off the agent",
             ((ROUTING, "                context_pool=pool if isinstance(pool, int) and pool > 0 else None,\n",
               "                context_pool=None,\n"),),
             "gateway"),
    Sabotage("pick builds no budget",
             ((ROUTING, "        client.budget = self._budget_for(resolution, picked, affinity, outcome)\n",
               "        client.budget = None\n"),),
             "gateway"),
    Sabotage("an attempt does not move the reservation to its backend",
             ((CLIENT, "        if self.budget is not None:\n            self.budget.enter(candidate)\n",
               "        pass\n"),),
             "gateway"),
    Sabotage("the stream never gives its room back",
             ((CLIENT, "            async with contextlib.aclosing(self._stream(request)) as events:\n"
                       "                async for event in events:\n                    yield event\n"
                       "        finally:\n            self._release()\n",
               "            async with contextlib.aclosing(self._stream(request)) as events:\n"
               "                async for event in events:\n                    yield event\n"
               "        finally:\n            pass\n"),),
             "gateway"),
    # --- CB3: a full pool at the doors -----------------------------------------------
    Sabotage("a full pool is described as an engine still loading",
             ((INFERENCE, "    if capacity_refused(e):\n        # CB3: every replica tried",
               "    if False:\n        # CB3: every replica tried"),),
             "gateway"),
    Sabotage("Codex is told the context is full before the stream",
             ((RESPONSES, "    if error_type == OVERLOADED:\n        # llama-server's words",
               "    if False:\n        # llama-server's words"),),
             "gateway"),
    Sabotage("Codex is told the context is full mid-stream",
             ((RESPONSES, '    if error_type == OVERLOADED:\n        return "server_error"',
               '    if False:\n        return "server_error"'),),
             "gateway"),
    Sabotage("Claude Code is told api_error mid-stream",
             ((INFERENCE, '                kind="overloaded_error" if capacity_refused(e) else "api_error",\n',
               '                kind="api_error",\n'),),
             "gateway"),
    Sabotage("the Anthropic stream ignores the kind it is given",
             ((ANTHROPIC, '                {"type": "error", "error": {"type": kind, "message": message}},\n',
               '                {"type": "error", "error": {"type": "api_error", "message": message}},\n'),),
             "gateway"),
    # --- CB1: affinity under every strategy -----------------------------------------
    Sabotage("affinity cannot be turned off",
             ((ROUTING, "        if not self.affinity_on():\n            affinity = None\n", ""),),
             "gateway"),
    Sabotage("affinity is never on",
             ((ROUTING, "        return self._affinity_on() is not False\n", "        return False\n"),),
             "gateway"),
    Sabotage("the setting never reaches the table",
             ((APP, '                affinity=lambda: store.get("conversationAffinity"),\n', ""),),
             "gateway"),
    Sabotage("the old word is recorded as the placement",
             ((ROUTING, "        if value in (SPREAD, LEAST_BUSY, ROUND_ROBIN):\n",
               "        if value in (SPREAD, LEAST_BUSY, ROUND_ROBIN, CONVERSATION):\n"),),
             "gateway"),
    Sabotage("each request records the stored word, not what ran",
             ((INFERENCE, "            strategy=table.placement() if table is not None else None,\n",
               '            strategy=str(store.get("loadBalancing")) if store is not None else None,\n'),),
             "gateway"),
    Sabotage("a stored conversation is kept as a choice",
             ((CONFIG, "        unchosen = raw is None or raw == LEGACY_CONVERSATION or marker.exists()\n",
               "        unchosen = raw is None or marker.exists()\n"),),
             "gateway"),
    Sabotage("a value written as the default never follows the next default",
             ((CONFIG, "        unchosen = raw is None or raw == LEGACY_CONVERSATION or marker.exists()\n",
               "        unchosen = raw is None or raw == LEGACY_CONVERSATION\n"),),
             "gateway"),
    Sabotage("a chosen value does not clear the marker",
             ((CONFIG, "                    self._mark_load_balancing_default_locked(new_value is None)\n",
               "                    pass\n"),),
             "gateway"),
    # --- CB2: spread -----------------------------------------------------------------
    Sabotage("spread ignores what each replica holds",
             ((ROUTING, "                    held.get(b.key, 0) / b.parallel_slots,\n",
               "                    0,\n"),),
             "gateway"),
    Sabotage("spread does not count per slot",
             ((ROUTING, "                    held.get(b.key, 0) / b.parallel_slots,\n",
               "                    held.get(b.key, 0),\n"),),
             "gateway"),
    Sabotage("spread breaks no tie by requests in flight",
             ((ROUTING, "                    self.inflight(b.key) / b.parallel_slots,\n                ),\n",
               "                    0,\n                ),\n"),),
             "gateway"),
    Sabotage("a conversation is counted against its own placement",
             ((AFFINITY, "                if entry_target != target or key == besides or now - seen > self._ttl:\n",
               "                if entry_target != target or now - seen > self._ttl:\n"),),
             "gateway"),
    Sabotage("an expired conversation is still held",
             ((AFFINITY, "                if entry_target != target or key == besides or now - seen > self._ttl:\n",
               "                if entry_target != target or key == besides:\n"),),
             "gateway"),
    Sabotage("the default placement is still least busy",
             ((ROUTING, "DEFAULT_PLACEMENT = SPREAD\n", "DEFAULT_PLACEMENT = LEAST_BUSY\n"),),
             "gateway"),
    Sabotage("the setting's default is still least busy",
             ((CONFIG, '        default="spread",\n', '        default="least_busy",\n'),),
             "gateway"),
    # --- CB5: evictions ---------------------------------------------------------------
    Sabotage("an eviction is never recorded",
             ((CLIENT, "            self.affinity = EVICTED\n", "            pass\n"),),
             "gateway"),
    Sabotage("a failed-over turn is judged against another replica",
             ((CLIENT, "            and candidate is convo.home\n", ""),),
             "gateway"),
    Sabotage("a turn that reused exactly its last prompt is evicted",
             ((CLIENT, "            and cached < convo.previous_prompt\n",
               "            and cached <= convo.previous_prompt\n"),),
             "gateway"),
    Sabotage("a conversation's prompt is never kept without a pool",
             ((CLIENT, "            convo.sizes.put(convo.target, convo.key, prompt, chars)\n",
               "            pass\n"),),
             "gateway"),
    Sabotage("pick names no conversation",
             ((ROUTING, "        if affinity is not None:\n            seen = self._sizes.get(",
               "        if False:\n            seen = self._sizes.get("),),
             "gateway"),
    Sabotage("evictions are not counted per group",
             ((METRICS, '                    "_affinity": {"hit": 0, "new": 0, "moved": 0, "evicted": 0},\n',
               '                    "_affinity": {"hit": 0, "new": 0, "moved": 0},\n'),),
             "gateway"),
    Sabotage("a v11 store is set aside rather than moved on",
             ((METRICS, "        if row is not None and int(row[0]) in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11):\n",
               "        if row is not None and int(row[0]) in (2, 3, 4, 5, 6, 7, 8, 9, 10):\n"),),
             "gateway"),
    # --- CB4: slot pinning, safely ----------------------------------------------------
    Sabotage("a turn whose slot is busy is given it anyway",
             ((SLOTS, "            if slot in self._busy:\n                # Its own slot",
               "            if False:\n                # Its own slot"),),
             "driver"),
    Sabotage("a new conversation may take a busy slot",
             ((SLOTS, "        idle = [slot for slot in range(self.total) if slot not in self._busy]\n",
               "        idle = list(range(self.total))\n"),),
             "driver"),
    Sabotage("the most recently used conversation gives up its slot",
             ((SLOTS, "            slot = min(idle, key=lambda s: order.index(owned[s]))\n",
               "            slot = max(idle, key=lambda s: order.index(owned[s]))\n"),),
             "driver"),
    Sabotage("an owned slot is taken while an unowned one is idle",
             ((SLOTS, "        if unowned:\n            slot = unowned[0]\n",
               "        if False:\n            slot = unowned[0]\n"),),
             "driver"),
    Sabotage("a slot is never released",
             ((SLOTS, "            self._busy.discard(slot)\n", "            pass\n"),),
             "driver"),
    Sabotage("a waiter is never woken",
             ((SLOTS, "                self._freed.set()\n", "                pass\n"),),
             "driver"),
    Sabotage("a chat turn names no slot",
             ((OPENAI, '            payload["id_slot"] = slot\n        hint = _attachment_hint(',
               '            pass\n        hint = _attachment_hint('),),
             "driver"),
    Sabotage("a stream holds no slot",
             ((OPENAI, '        the slot is held busy until the stream ends, however it ends."""\n'
                       "        pins = await self._slot_map() if request.audioOutput is None else None\n",
               '        the slot is held busy until the stream ends, however it ends."""\n'
               "        pins = None\n"),),
             "driver"),
    Sabotage("the setting is never read",
             ((OPENAI, '            slot_pinning=get("slotPinning") is True,\n',
               "            slot_pinning=False,\n"),),
             "driver"),
    Sabotage("a truthy string pins",
             ((OPENAI, '            slot_pinning=get("slotPinning") is True,\n',
               '            slot_pinning=bool(get("slotPinning")),\n'),),
             "driver"),
    Sabotage("pinning is on whatever the setting",
             ((OPENAI, "        if not self._slot_pinning:\n            return None\n", ""),),
             "driver"),
    Sabotage("the gateway never tells the driver the conversation",
             ((CLIENT, '        return request.model_copy(update={"conversationKey": self.conversation.key})\n',
               "        return request\n"),),
             "gateway"),
    Sabotage("the profile flag does not reach the companion",
             ((LLAMA, '        return {"slotPinning": True} if flags.get(SLOT_PINNING_KEY) is True else {}\n',
               "        return {}\n"),),
             "agent"),
    Sabotage("the profile flag does not reach the engine",
             ((LLAMA, '    SLOT_PINNING_KEY: "--no-cache-idle-slots",\n', ""),),
             "agent"),
    Sabotage("a companion that was pinning keeps pinning when the flag goes",
             ((COMPANIONS, '        "slotPinning": None,\n', ""),),
             "agent"),
    # --- CB3b: the agent's pool ------------------------------------------------------
    Sabotage("every pool is called shared",
             ((LLAMA, "        return context if unified else None\n", "        return context\n"),),
             "agent"),
    Sabotage("an explicit slot count does not divide the pool",
             ((LLAMA, '        automatic = parallel is None or parallel.strip() == "-1"\n',
               "        automatic = True\n"),),
             "agent"),
    Sabotage("--no-kv-unified is ignored",
             ((LLAMA, '            elif name in ("-no-kvu", "--no-kv-unified"):\n                unified = False\n',
               '            elif name in ("-no-kvu", "--no-kv-unified"):\n                pass\n'),),
             "agent"),
    Sabotage("the environment's slot count is ignored",
             ((LLAMA, '        parallel: str | None = env.get("LLAMA_ARG_N_PARALLEL")\n',
               "        parallel: str | None = None\n"),),
             "agent"),
    Sabotage("the pool never reaches the runtime",
             ((RUNTIMES, '                    capabilities = capabilities.model_copy(update={"contextPoolTokens": pool})\n',
               "                    pass\n"),),
             "agent"),
]


def run_gate(gate: str) -> int:
    command, cwd = GATES[gate]
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=300,
                                stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        # A gate that hangs has seen the sabotage too: a slot never given
        # back leaves the next request waiting for ever.
        print(f"    [{gate}] hung past 300 s", flush=True)
        return 124
    lines = (result.stdout + result.stderr).strip().splitlines()
    print(f"    [{gate}] exit={result.returncode}  {lines[-1] if lines else ''}", flush=True)
    return result.returncode


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only and only.startswith("--from="):
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
            if run_gate(gate) != 0:
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
                code = run_gate(sabotage.gate)
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
