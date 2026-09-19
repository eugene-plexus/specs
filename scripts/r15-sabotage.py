"""R1.5 + R1.6 sabotage pass: every check must fail when its defect is
put back.

Run it after `r15-acceptance.sh`, and before believing either. Roadmap
§2.5 and §2.6; record `docs/acceptance/a-hostile-box-run.md` §5.

Restores from a COPY taken before anything is touched, never
`git checkout --`: that reverts uncommitted work, which in this repo
means deleting the change under test, after which every later result
reads *caught* for the wrong reason.

Opens with a baseline -- every gate passes unsabotaged -- because a
sabotage that "fails" against an already-red gate proves nothing.

**The first entries are the findings themselves**, each put back the way
the repo actually had it. The ones after them take each fix apart a
property at a time, on whichever gate can see them.

Four gates, because these two slices are three components and a browser
type: the agent's unit file, the gateway's two-node file, the UI's issue
rules, and the UI page that has to be wired to them.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")
SPECS = ROOT / "specs"

# --- the files each sabotage touches -----------------------------------
STATE = "src/eugene_plexus_agent/state.py"
APP = "src/eugene_plexus_agent/app.py"
HEALTH = "src/eugene_plexus_agent/routes/health.py"
AUTH = "src/eugene_plexus_agent/routes/auth.py"
PORTS = "src/eugene_plexus_agent/ports.py"
TOPOLOGY = "src/eugene_plexus_agent/default_topology.py"
AGENT_RUNTIMES = "src/eugene_plexus_agent/runtimes.py"
AGENT_ROUTE = "src/eugene_plexus_agent/routes/runtimes.py"
ACQUISITION = "src/eugene_plexus_agent/engines/acquisition.py"

ROUTING = "src/eugene_plexus_gateway/routing.py"
LIFECYCLE = "src/eugene_plexus_gateway/lifecycle.py"

ISSUES = "src/lib/issues.ts"
USE_ISSUES = "src/lib/useIssues.ts"
VOCAB = "src/lib/vocabulary.ts"
START = "src/app/setup/start.ts"

AGENT = "agent"
GATEWAY = "gateway"
UI_ISSUES = "ui:issues"
UI_HOME = "ui:home"
UI_VOCAB = "ui:vocab"


def run_gate(gate: str) -> tuple[int, str]:
    """Run one gate.

    Every child is decoded as UTF-8 explicitly: vitest writes check
    marks, Python's default on Windows is cp1252, and a reader thread
    raising `UnicodeDecodeError` reports a green suite as a red gate.
    """
    if gate == AGENT:
        done = subprocess.run(
            [
                str(ROOT / AGENT / ".venv" / "Scripts" / "python.exe"),
                "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
                "-W", "ignore::DeprecationWarning",
                "tests/test_a_hostile_box.py",
            ],
            cwd=ROOT / AGENT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=900,
        )
    elif gate == GATEWAY:
        done = subprocess.run(
            [
                str(ROOT / GATEWAY / ".venv" / "Scripts" / "python.exe"),
                "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
                "-W", "ignore::DeprecationWarning",
                "tests/test_multi_agent.py",
            ],
            cwd=ROOT / GATEWAY, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=900,
        )
    else:
        # Through bash, not `cmd /c`: under cmd, vitest reports *"Vitest
        # failed to find the current suite"* from its own setup file and
        # comes back with `no tests`. A runner that invokes a gate
        # differently from the way a person does reports on something
        # else.
        spec = {
            UI_ISSUES: "src/lib/issues.test.ts src/lib/useIssues.test.tsx",
            UI_HOME: "src/app/page.test.tsx",
            UI_VOCAB: "src/lib/vocabulary.test.ts src/app/setup/page.test.tsx",
        }[gate]
        done = subprocess.run(
            ["bash", "-lc", f"cd /d/py/eugene-plexus/ui && npx vitest run {spec}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
        )
    return done.returncode, (done.stdout or "")[-2500:] + (done.stderr or "")[-800:]


SABOTAGES: list[tuple[str, str, str, str, str, str]] = [
    # ================================================================= #
    # R1.5 -- the findings, put back
    # ================================================================= #
    (
        "agent: `/v1/engines` runs on the event loop again (#5, THE finding)",
        AGENT, AGENT_ROUTE,
        "    engines = await asyncio.to_thread(describe_engines, get_config=state.get_config)",
        "    engines = describe_engines(get_config=state.get_config)",
        AGENT,
    ),
    (
        "agent: the host is resolved once per adapter again (#5)",
        AGENT, AGENT_RUNTIMES,
        "        acquisition = _acquisition_for(kind, host)",
        "        acquisition = _acquisition_for(kind, detect_host())",
        AGENT,
    ),
    (
        "agent: `plan_for` resolves the host for itself again (#5)",
        AGENT, AGENT_RUNTIMES,
        "    detected = host if host is not None else detect_host()",
        "    detected = detect_host()",
        AGENT,
    ),
    (
        "agent: a failed release check is not stamped (#5)",
        AGENT, ACQUISITION,
        "            self._failed_at = now\n",
        "",
        AGENT,
    ),
    (
        "agent: the metadata read takes a download's patience again (#5)",
        AGENT, ACQUISITION,
        "_METADATA_TIMEOUT_SECONDS = 10.0",
        "_METADATA_TIMEOUT_SECONDS = 60.0",
        AGENT,
    ),
    (
        "agent: `agent.yaml` is truncated before it is written (#6, THE finding)",
        AGENT, STATE,
        """        tmp = self._path.with_suffix(self._path.suffix + f".tmp-{os.getpid()}")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                yaml.safe_dump(out, f, sort_keys=True, default_flow_style=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except BaseException:""",
        """        with self._path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(out, f, sort_keys=True, default_flow_style=False)
        tmp = self._path.with_suffix(self._path.suffix + f".tmp-{os.getpid()}")
        try:
            pass
        except BaseException:""",
        AGENT,
    ),
    (
        "agent: the config load is uncaught again (#6, THE finding)",
        AGENT, APP,
        "        config_error = state.load_or_degrade()",
        "        state.load()\n        config_error = None",
        AGENT,
    ),
    (
        "agent: a degraded boot says nothing on the wire (#6)",
        AGENT, HEALTH,
        "    if reason:",
        "    if False:",
        AGENT,
    ),
    (
        "agent: a file that held a passphrase invites the wizard again (#6)",
        AGENT, AUTH,
        "    if state.lost_its_passphrase():",
        "    if False:",
        AGENT,
    ),
    (
        "agent: seeding takes the port whatever is on it (#7, THE finding)",
        AGENT, TOPOLOGY,
        "        port = ports.first_free(component.port, reserved=RESERVED_PORTS | taken)",
        "        port = component.port",
        AGENT,
    ),
    (
        "agent: the 409 sends a person into agent.yaml again (#7)",
        AGENT, AUTH,
        '            "This install already has a passphrase. Sign in with it instead of setting it "\n'
        '            "up again. If you have forgotten it, there is no recovery: the install\'s keys "\n'
        '            "are sealed with it.",',
        '            "This install already has a passphrase set. Use the change-"\n'
        '            "passphrase flow (planned v0.3) or reset the install by "\n'
        '            "removing agent.yaml\'s auth block by hand.",',
        AGENT,
    ),
    # --- taking the R1.5 fixes apart --------------------------------------
    (
        # **ESCAPES ON PURPOSE, and the escape is recorded rather than
        # papered over.** An actively listening socket refuses a second
        # bind on both platforms without this option, so what removing it
        # loses is only the `TIME_WAIT` case -- which no check here can
        # arrange deterministically. It stays in the list so the next
        # person sees that it is uncovered rather than assuming it is
        # not; `ports.is_free`'s docstring says the same. The option that
        # WOULD break the probe outright is `SO_REUSEADDR`, and the entry
        # below is the one that matters.
        "agent: the port probe drops SO_EXCLUSIVEADDRUSE (uncovered, by measurement)",
        AGENT, PORTS,
        '        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)',
        "        exclusive = None",
        AGENT,
    ),
    (
        # Kept beside it because it was EXPECTED to be the one that
        # breaks the probe and measurably is not: against a listening
        # socket, `SO_REUSEADDR` refuses with errno 13 rather than
        # succeeding. Two uncovered entries, one measured reason.
        "agent: the port probe sets SO_REUSEADDR (uncovered, by measurement)",
        AGENT, PORTS,
        '        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)',
        "        exclusive = socket.SO_REUSEADDR",
        AGENT,
    ),
    (
        "agent: the walk prefers the next port over the documented one",
        AGENT, PORTS,
        "    for candidate in range(preferred, preferred + limit):",
        "    for candidate in range(preferred + 1, preferred + limit):",
        AGENT,
    ),
    (
        "agent: a degraded load keeps the half-parsed state it raised on",
        AGENT, STATE,
        """            with self._lock:
                self._config = _config_defaults()
                self._components = {}
                self._runtimes = {}
                self._auth = {}
                self._degraded_reason = reason""",
        """            with self._lock:
                self._degraded_reason = reason""",
        AGENT,
    ),
    (
        "agent: `firstRunComplete` counts as evidence of a passphrase again",
        AGENT, STATE,
        """            return self._lost_passphrase""",
        """            return self._lost_passphrase or bool(self._config.get("firstRunComplete"))""",
        AGENT,
    ),
    (
        "agent: the interrupted write leaves its temp file behind",
        AGENT, STATE,
        "            tmp.unlink(missing_ok=True)\n            raise",
        "            raise",
        AGENT,
    ),
    # ================================================================= #
    # R1.6 -- the finding, put back
    # ================================================================= #
    (
        "gateway: runtimes are merged by bare name again (#8, THE finding)",
        GATEWAY, ROUTING,
        "            facts[(owner, name)] = _RuntimeFacts(",
        "            facts[(None, name)] = _RuntimeFacts(",
        GATEWAY,
    ),
    (
        "gateway: a driver joins to any node's runtime of that name (#8)",
        GATEWAY, ROUTING,
        "                backend.runtime = runtimes.get((backend.node, backend.info.runtime))",
        "                backend.runtime = next(\n"
        "                    (f for k, f in runtimes.items() if k[1] == backend.info.runtime),\n"
        "                    None,\n"
        "                )",
        GATEWAY,
    ),
    (
        "gateway: the in-flight counters share a bucket across nodes (#8)",
        GATEWAY, ROUTING,
        "        key: Key = (node, driver)\n        self._inflight[key] = self._inflight.get(key, 0) + 1",
        "        key: Key = (None, driver)\n        self._inflight[key] = self._inflight.get(key, 0) + 1",
        GATEWAY,
    ),
    (
        "gateway: the idle clock is shared across nodes (#8)",
        GATEWAY, ROUTING,
        "            self._runtime_last_request[runtime] = now",
        "            self._runtime_last_request[(None, runtime[1])] = now",
        GATEWAY,
    ),
    (
        # Relabelled after the pass: this edit changes the RESERVATION
        # key, not which agent is asked -- `agent_url_for(facts)` is a
        # separate read and the two-node idle test already asserts the
        # host. It is the same property as the reservation sabotage
        # below, on the write side, and its check is
        # `test_a_stop_in_flight_holds_out_only_the_replica_it_is_for`.
        "gateway: the stop reservation is WRITTEN by bare name (#8)",
        GATEWAY, LIFECYCLE,
        "            with self._table.stopping(facts.key):",
        "            with self._table.stopping((None, facts.name)):",
        GATEWAY,
    ),
    (
        "gateway: one wake in flight answers for both replicas (#8)",
        GATEWAY, LIFECYCLE,
        "        task = self._waking.get(facts.key)",
        "        task = self._waking.get((None, facts.name))",
        GATEWAY,
    ),
    (
        "gateway: the aliases fallback crosses nodes again (#8)",
        GATEWAY, ROUTING,
        "                backend.runtime = by_alias.get((backend.node, model_id))",
        "                backend.runtime = next(\n"
        "                    (f for k, f in by_alias.items() if k[1] == model_id), None\n"
        "                )",
        GATEWAY,
    ),
    (
        "gateway: a driver's node is dropped, so every key collapses (#8)",
        GATEWAY, ROUTING,
        "            name=name, url=url, client=client, info=info, node=node, stopping=self._stopping",
        "            name=name, url=url, client=client, info=info, node=None, stopping=self._stopping",
        GATEWAY,
    ),
    (
        "gateway: the stop reservation is read by bare name again (#8)",
        GATEWAY, ROUTING,
        "        if self.runtime is not None and self.stopping.get(self.runtime.key, 0) > 0:",
        "        if self.runtime is not None and self.stopping.get((None, self.runtime.name), 0) > 0:",
        GATEWAY,
    ),
    (
        "gateway: `Resolution.runtimes` dedupes on the name again (#8)",
        GATEWAY, ROUTING,
        "            if facts is not None and facts.key not in seen:\n                seen.add(facts.key)",
        "            if facts is not None and facts.name not in seen:\n                seen.add(facts.name)",
        GATEWAY,
    ),
    (
        "gateway: routable-on-faith goes back to DEBUG",
        GATEWAY, ROUTING,
        "                    log.warning(\n"
        '                        "driver %r on node %r follows runtime %r, which that node does not "',
        "                    log.debug(\n"
        '                        "driver %r on node %r follows runtime %r, which that node does not "',
        GATEWAY,
    ),
    # ================================================================= #
    # R1.5 -- the UI half
    # ================================================================= #
    (
        "ui: there is no `component-down` issue kind again (#7, THE finding)",
        "ui", ISSUES,
        "      ...componentDownIssues(node),\n",
        "",
        UI_ISSUES,
    ),
    (
        "ui: nothing reads `/v1/components`, so the card has no material (#7)",
        "ui", USE_ISSUES,
        '    api.get<ComponentList>(address.target, "/v1/components", options).catch(() => null),',
        "    Promise.resolve(null),",
        UI_ISSUES,
    ),
    (
        "ui: Home renders the card but the poll never fetches components (#7)",
        "ui", USE_ISSUES,
        '    api.get<ComponentList>(address.target, "/v1/components", options).catch(() => null),',
        "    Promise.resolve(null),",
        UI_HOME,
    ),
    (
        "ui: a crashed component is reported as a warning, not as down",
        "ui", ISSUES,
        '      kind: "component-down",\n      severity: "blocking",',
        '      kind: "component-down",\n      severity: "warning",',
        UI_ISSUES,
    ),
    (
        "ui: `starting` counts, so every restart raises an issue",
        "ui", ISSUES,
        '    if (component.status !== "crashed" && component.status !== "unreachable") continue;',
        '    if (component.status === "running") continue;',
        UI_ISSUES,
    ),
    (
        "ui: the reason the agent recorded is dropped from the row",
        "ui", ISSUES,
        "      detail: component.lastError\n"
        "        ? `It stopped and has not come back. The last thing it said was: ${component.lastError}`",
        "      detail: false\n"
        "        ? `It stopped and has not come back. The last thing it said was: ${component.lastError}`",
        UI_HOME,
    ),
    (
        "ui: every component links to Inference, so the gateway's fix is elsewhere",
        "ui", ISSUES,
        '  if (component.kind === "inference-driver") return "/inference";',
        '  if (true) return "/inference";',
        UI_HOME,
    ),
    (
        "ui: the extractor stops reading backtick copy (#35, THE finding)",
        "ui", VOCAB,
        "  for (const m of body.matchAll(/`([^`\\\\\\n]{4,})`/g)) {",
        "  for (const m of [] as RegExpMatchArray[]) {",
        UI_VOCAB,
    ),
    (
        "ui: the wizard names the trust root again (#35)",
        "ui", START,
        "    `The control root did not take the passphrase (${because}).` +",
        "    `The trust root would not accept a passphrase (${because}).` +",
        UI_VOCAB,
    ),
    (
        "ui: the backtick pattern counts interpolation-only code as copy",
        "ui", VOCAB,
        "    if (text && looksLikeProse(text)) visible.push(text);",
        "    if (text) visible.push(text);",
        UI_VOCAB,
    ),
]


def main() -> int:
    backup = Path(tempfile.mkdtemp(prefix="r15-sabotage-"))
    touched = {(repo, rel) for _, repo, rel, _, _, _ in SABOTAGES}
    for repo, rel in touched:
        dst = backup / repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / repo / rel, dst)
    print(f"copies in {backup}\n")

    gates = sorted({g for *_, g in SABOTAGES})
    failures = []
    for gate in gates:
        code, out = run_gate(gate)
        print(f"[baseline] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            failures.append(f"baseline {gate}\n{out}")
    if failures:
        print("\nBASELINE FAILED - a sabotage result would mean nothing.")
        print("\n".join(failures))
        return 1
    print()

    caught = escaped = 0
    for label, repo, rel, old, new, gate in SABOTAGES:
        path = ROOT / repo / rel
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run_gate(gate)
        finally:
            shutil.copy2(backup / repo / rel, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}\n{out}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(SABOTAGES)} sabotages")

    for gate in gates:
        code, out = run_gate(gate)
        print(f"[restored] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
