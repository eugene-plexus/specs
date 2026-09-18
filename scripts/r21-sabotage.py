"""R2.1 sabotage pass: every check must fail when its defect is put back.

Run it after `r21-acceptance.sh`, and before believing either. Roadmap
§3.1; record `docs/acceptance/node-read-failures-run.md` §3.

Restores from a COPY taken before anything is touched, never
`git checkout --`: that reverts uncommitted work, which in this repo
means deleting the change under test, after which every later result
reads *caught* for the wrong reason.

Opens with a baseline — the gate passes unsabotaged — because a sabotage
that "fails" against an already-red gate proves nothing at all.

**The first three entries are the findings themselves**, each put back
the way the repo actually had it: `[]` for a failed components read,
`{}` for a failed runtimes read, and no reservation around the stop
call. The entries after them take the fix apart one property at a time —
the flag without the fallback, the fallback without the flag, a
reservation that is a flag rather than a count, and a reservation with
no `finally`.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")

GATES = {
    "gateway": "tests/test_node_read_failures.py",
}

ROUTING = "src/eugene_plexus_gateway/routing.py"
LIFECYCLE = "src/eugene_plexus_gateway/lifecycle.py"
GATE = "tests/test_node_read_failures.py"

SABOTAGES = [
    # -- the findings -----------------------------------------------------
    (
        "gateway: a failed components read is an empty topology again (#9, THE finding)",
        "gateway",
        ROUTING,
        '            log.warning("could not read %s/v1/components; keeping what it last '
        'declared", agent_url)\n'
        "            return [], False",
        '            log.warning("could not read %s/v1/components; nothing from it is '
        'routable", agent_url)\n'
        "            return [], True",
        GATE,
    ),
    (
        "gateway: a failed runtimes read is no runtimes again (#18, THE finding)",
        "gateway",
        ROUTING,
        '            log.warning(\n'
        '                "could not read %s/v1/runtimes; keeping the facts from its last answer",'
        " agent_url\n"
        "            )\n"
        "            return {}, False",
        "            return {}, True",
        GATE,
    ),
    (
        "gateway: the idle pass stops without a reservation (#17, THE finding)",
        "gateway",
        LIFECYCLE,
        "            with self._table.stopping(facts.name):\n"
        '                unloaded = await self._client.stop(agent_url, facts.name, reason="idle")',
        '            unloaded = await self._client.stop(agent_url, facts.name, reason="idle")',
        f"{GATE}::test_the_idle_pass_reserves_the_runtime_across_the_stop_call",
    ),
    (
        "gateway: an eviction stops without a reservation",
        "gateway",
        LIFECYCLE,
        "            with self._table.stopping(victim):\n"
        '                evicted_ok = await self._client.stop(agent_url, victim, reason="idle")',
        '            evicted_ok = await self._client.stop(agent_url, victim, reason="idle")',
        f"{GATE}::test_an_eviction_reserves_each_victim",
    ),
    # -- the flag and the fallback are two halves --------------------------
    (
        # The fetchers report the failure honestly and the caller ignores
        # it. This is the half a reviewer would assume is the whole fix.
        "gateway: the components fallback is dropped, the flag kept",
        "gateway",
        ROUTING,
        "            entries = list(self._last_entries.get(node, []))",
        "            entries = []",
        GATE,
    ),
    (
        "gateway: the runtimes fallback is dropped, the flag kept",
        "gateway",
        ROUTING,
        "            runtimes = dict(self._last_facts.get(node, {}))",
        "            runtimes = {}",
        GATE,
    ),
    (
        # The opposite half: the fallback exists but a failed read is
        # cached as though it were an answer, so the first failure erases
        # the node permanently.
        "gateway: a failed read overwrites the cache it is meant to fall back to",
        "gateway",
        ROUTING,
        "        if entries_ok:\n            self._last_entries[node] = entries",
        "        if True:\n            self._last_entries[node] = entries",
        GATE,
    ),
    (
        "gateway: the runtime facts cache is written on a failed read too",
        "gateway",
        ROUTING,
        "        if runtimes_ok:\n            self._last_facts[node] = runtimes",
        "        if True:\n            self._last_facts[node] = runtimes",
        GATE,
    ),
    (
        # Keeping a node that did not answer must not become keeping one
        # that answered and no longer declares the driver.
        "gateway: a driver dropped by a SUCCESSFUL read is kept anyway",
        "gateway",
        ROUTING,
        "        if entries_ok:\n            self._last_entries[node] = entries\n"
        "        else:\n            entries = list(self._last_entries.get(node, []))",
        "        if entries_ok:\n"
        "            entries = list(self._last_entries.get(node, [])) + [\n"
        "                e for e in entries if e not in self._last_entries.get(node, [])\n"
        "            ]\n"
        "            self._last_entries[node] = entries\n"
        "        else:\n            entries = list(self._last_entries.get(node, []))",
        f"{GATE}::test_a_successful_read_that_drops_a_driver_still_closes_its_client",
    ),
    # -- the reservation, one property at a time ---------------------------
    (
        "gateway: the eligibility rule ignores the reservation",
        "gateway",
        ROUTING,
        "        if self.runtime is not None and self.stopping.get(self.runtime.name, 0) > 0:\n"
        "            return False\n"
        "        return self.runtime is None or self.runtime.status == READY",
        "        return self.runtime is None or self.runtime.status == READY",
        GATE,
    ),
    (
        "gateway: the reason does not say the runtime is being stopped",
        "gateway",
        ROUTING,
        "        if self.stopping.get(self.runtime.name, 0) > 0:\n"
        '            return f"runtime {self.runtime.name!r} is being stopped"\n',
        "",
        f"{GATE}::test_a_runtime_being_stopped_is_not_routed_to",
    ),
    (
        # The subtle one: every backend gets its OWN empty map, so the
        # reservation is real, correct, and invisible to routing.
        "gateway: the probe does not share the table's reservation map",
        "gateway",
        ROUTING,
        "        return _Backend(name=name, url=url, client=client, info=info, "
        "stopping=self._stopping)",
        "        return _Backend(name=name, url=url, client=client, info=info)",
        GATE,
    ),
    (
        "gateway: the reservation is a flag rather than a count",
        "gateway",
        ROUTING,
        "        self._stopping[runtime] = self._stopping.get(runtime, 0) + 1\n"
        "        try:\n"
        "            yield\n"
        "        finally:\n"
        "            remaining = self._stopping.get(runtime, 1) - 1\n"
        "            if remaining > 0:\n"
        "                self._stopping[runtime] = remaining\n"
        "            else:\n"
        "                self._stopping.pop(runtime, None)",
        "        self._stopping[runtime] = 1\n"
        "        try:\n"
        "            yield\n"
        "        finally:\n"
        "            self._stopping.pop(runtime, None)",
        f"{GATE}::test_two_overlapping_stops_do_not_release_each_other",
    ),
    (
        "gateway: the reservation is released on the happy path only",
        "gateway",
        ROUTING,
        "        try:\n"
        "            yield\n"
        "        finally:\n"
        "            remaining = self._stopping.get(runtime, 1) - 1",
        "        if True:\n"
        "            yield\n"
        "        if True:\n"
        "            remaining = self._stopping.get(runtime, 1) - 1",
        f"{GATE}::test_a_stop_that_raises_releases_the_reservation",
    ),
    (
        "gateway: a node that really left keeps its cached topology",
        "gateway",
        ROUTING,
        "        for known in list(self._last_entries):\n"
        "            if known not in agents:\n"
        "                self._last_entries.pop(known, None)",
        "        pass",
        f"{GATE}::test_a_node_that_leaves_the_install_keeps_nothing",
    ),
]


def run(repo: str, selector: str) -> tuple[int, str]:
    py = ROOT / repo / ".venv" / "Scripts" / "python.exe"
    done = subprocess.run(
        [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", selector],
        cwd=ROOT / repo,
        capture_output=True,
        text=True,
        timeout=900,
    )
    return done.returncode, done.stdout[-1500:] + done.stderr[-500:]


def main() -> int:
    backup = Path(tempfile.mkdtemp(prefix="r21-sabotage-"))
    touched = {(repo, rel) for _, repo, rel, _, _, _ in SABOTAGES}
    for repo, rel in touched:
        dst = backup / repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / repo / rel, dst)
    print(f"copies in {backup}\n")

    failures: list[str] = []
    for repo, gate in sorted(GATES.items()):
        code, out = run(repo, gate)
        print(f"[baseline] {repo}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            failures.append(f"baseline {repo}\n{out}")
    if failures:
        print("\nBASELINE FAILED - a sabotage result would mean nothing.")
        print("\n".join(failures))
        return 1
    print()

    caught = escaped = 0
    for label, repo, rel, old, new, selector in SABOTAGES:
        path = ROOT / repo / rel
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run(repo, selector)
        finally:
            shutil.copy2(backup / repo / rel, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}\n{out}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(SABOTAGES)} sabotages")

    for repo, gate in sorted(GATES.items()):
        code, out = run(repo, gate)
        print(f"[restored] {repo}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
