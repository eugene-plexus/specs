"""R1.4 sabotage pass: every check must fail when its defect is put back.

Run it after `r14-acceptance.sh`, and before believing either. Roadmap
§2.4; record `docs/acceptance/stream-bookkeeping-run.md` §3.

Restores from a COPY taken before anything is touched, never
`git checkout --`: that reverts uncommitted work, which in this repo
means deleting the change under test, after which every later result
reads *caught* for the wrong reason.

Opens with a baseline — the gate passes unsabotaged — because a sabotage
that "fails" against an already-red gate proves nothing at all.

**The first two entries are the findings themselves.** Dropping the
`finally` arm is §6.1 #3 exactly as this slice found it, and it has to
fail the closed-tab check AND the cancelled-task check: they are two
different `BaseException`s arriving at the same place, and a fix that
covered one would be a fix for the symptom someone happened to press.
Restoring `served=True` is §6.3 #38.

The pair after them is the one the verification added: the counter has
to be undone against the runtime it was raised against, so both the
forward case (the decrement is skipped) and the mirror (a decrement
that was never earned) are put back separately.
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
    "gateway": "tests/test_stream_bookkeeping.py",
}

DRIVER_CLIENT = "src/eugene_plexus_gateway/driver_client.py"
ROUTING = "src/eugene_plexus_gateway/routing.py"
INFERENCE = "src/eugene_plexus_gateway/routes/inference.py"

# The `finally` arm, verbatim, so removing it is removing exactly the
# fix rather than something adjacent to it.
FINALLY_ARM = """                    if not reported and self._hooks is not None and driver:
                        ending = sys.exc_info()[1]
                        self._hooks.on_attempt_end(
                            driver,
                            runtime=runtime,
                            served=False,
                            elapsed_ms=int((time.perf_counter() - started) * 1000),
                            error=type(ending).__name__ if ending is not None else "Abandoned",
                        )
"""

SABOTAGES = [
    # -- the findings -----------------------------------------------------
    (
        "gateway: the attempt is never closed on an abandoned stream (#3, THE finding)",
        "gateway",
        DRIVER_CLIENT,
        FINALLY_ARM,
        "",
        "tests/test_stream_bookkeeping.py",
    ),
    (
        "gateway: a stream with no done frame is served again (#38, THE finding)",
        "gateway",
        DRIVER_CLIENT,
        "                            served=saw_done,",
        "                            served=True,",
        "tests/test_stream_bookkeeping.py",
    ),
    # -- each half of the finally arm, separately -------------------------
    (
        # If only the closed-tab check failed above, the cancellation
        # check would be asserting the fixture.
        "gateway: the finally arm only fires for GeneratorExit, not cancellation",
        "gateway",
        DRIVER_CLIENT,
        "                    if not reported and self._hooks is not None and driver:\n"
        "                        ending = sys.exc_info()[1]\n",
        "                    ending = sys.exc_info()[1]\n"
        "                    if (\n"
        "                        not reported\n"
        "                        and isinstance(ending, GeneratorExit)\n"
        "                        and self._hooks is not None\n"
        "                        and driver\n"
        "                    ):\n",
        "tests/test_stream_bookkeeping.py::test_a_cancelled_request_returns_the_counters_to_zero",
    ),
    (
        "gateway: the attempt is reported twice on the paths that already reported",
        "gateway",
        DRIVER_CLIENT,
        "                    if not reported and self._hooks is not None and driver:",
        "                    if self._hooks is not None and driver:",
        "tests/test_stream_bookkeeping.py",
    ),
    (
        "gateway: a cascaded failure is reported twice",
        "gateway",
        DRIVER_CLIENT,
        "                except Exception as exc:\n                    reported = True\n",
        "                except Exception as exc:\n",
        "tests/test_stream_bookkeeping.py::test_a_cascade_records_one_row_per_attempt",
    ),
    # -- `saw_done` itself -------------------------------------------------
    (
        # The other direction of #38's fix: a `saw_done` that is never
        # set turns every stream into a truncation, and the checks that
        # assert the failure would all still pass.
        "gateway: saw_done is never set, so nothing ever served",
        "gateway",
        DRIVER_CLIENT,
        "                        if event.done:\n                            saw_done = True\n",
        "",
        "tests/test_stream_bookkeeping.py::test_a_completed_stream_is_still_recorded_served",
    ),
    (
        "gateway: the truncation is recorded with no reason on the row",
        "gateway",
        DRIVER_CLIENT,
        "                            error=None if saw_done else \"IncompleteStream\",",
        "                            error=None,",
        "tests/test_stream_bookkeeping.py::test_a_stream_that_never_says_done_is_not_recorded_served",
    ),
    # -- the pairing -------------------------------------------------------
    (
        "gateway: on_attempt_end resolves the runtime itself again (the forward leak)",
        "gateway",
        ROUTING,
        "        self._inflight[driver] = max(0, self._inflight.get(driver, 0) - 1)\n"
        "        if runtime is not None:",
        "        self._inflight[driver] = max(0, self._inflight.get(driver, 0) - 1)\n"
        "        runtime = self._runtime_name_for_driver(driver)\n"
        "        if runtime is not None:",
        "tests/test_stream_bookkeeping.py",
    ),
    (
        "gateway: on_attempt_start no longer says which runtime it counted",
        "gateway",
        ROUTING,
        "            self._runtime_inflight[runtime] = self._runtime_inflight.get(runtime, 0) + 1\n"
        "        return runtime",
        "            self._runtime_inflight[runtime] = self._runtime_inflight.get(runtime, 0) + 1\n"
        "        return None",
        "tests/test_stream_bookkeeping.py",
    ),
    (
        "gateway: the slot drops the name on the way back through generate",
        "gateway",
        DRIVER_CLIENT,
        "                        self._hooks.on_attempt_end(\n"
        "                            driver,\n"
        "                            runtime=runtime,\n"
        "                            served=True,\n"
        "                            elapsed_ms=int((time.perf_counter() - started) * 1000),\n"
        "                        )\n"
        "                    self.served_by = driver\n"
        "                    self.tier = tier_index + 1\n"
        "                    return result\n"
        "        # Every backend failed in a cascade-eligible way. Re-raise the",
        "                        self._hooks.on_attempt_end(\n"
        "                            driver,\n"
        "                            runtime=None,\n"
        "                            served=True,\n"
        "                            elapsed_ms=int((time.perf_counter() - started) * 1000),\n"
        "                        )\n"
        "                    self.served_by = driver\n"
        "                    self.tier = tier_index + 1\n"
        "                    return result\n"
        "        # Every backend failed in a cascade-eligible way. Re-raise the",
        "tests/test_stream_bookkeeping.py::test_generate_pairs_its_counter_the_same_way",
    ),
    (
        "gateway: the embed path drops the name on the way back",
        "gateway",
        DRIVER_CLIENT,
        "                        self._hooks.on_attempt_end(\n"
        "                            driver,\n"
        "                            runtime=runtime,\n"
        "                            served=True,\n"
        "                            elapsed_ms=int((time.perf_counter() - started) * 1000),\n"
        "                        )\n"
        "                    self.served_by = driver\n"
        "                    self.tier = tier_index + 1\n"
        "                    return result\n"
        "        assert last_exc is not None\n",
        "                        self._hooks.on_attempt_end(\n"
        "                            driver,\n"
        "                            runtime=None,\n"
        "                            served=True,\n"
        "                            elapsed_ms=int((time.perf_counter() - started) * 1000),\n"
        "                        )\n"
        "                    self.served_by = driver\n"
        "                    self.tier = tier_index + 1\n"
        "                    return result\n"
        "        assert last_exc is not None\n",
        "tests/test_stream_bookkeeping.py::test_embed_pairs_its_counter_the_same_way",
    ),
    # -- the route half ----------------------------------------------------
    (
        "gateway: the done-less stream goes back to [DONE] with no terminal frame",
        "gateway",
        INFERENCE,
        "            if not emitted_role:\n"
        "                yield frame(\n"
        "                    envelope(delta=Delta(role=Role2.assistant), finish=None, model=body.model)\n"
        "                )\n"
        "            yield frame(envelope(delta=Delta(), finish=FinishReason.stop, model=body.model))\n",
        "",
        "tests/test_stream_bookkeeping.py"
        "::test_a_stream_that_never_says_done_still_gets_a_terminal_frame",
    ),
    (
        "gateway: the terminal frame is emitted with no finish reason on it",
        "gateway",
        INFERENCE,
        "            yield frame(envelope(delta=Delta(), finish=FinishReason.stop, model=body.model))",
        "            yield frame(envelope(delta=Delta(), finish=None, model=body.model))",
        "tests/test_stream_bookkeeping.py"
        "::test_a_stream_that_never_says_done_still_gets_a_terminal_frame",
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
    backup = Path(tempfile.mkdtemp(prefix="r14-sabotage-"))
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
