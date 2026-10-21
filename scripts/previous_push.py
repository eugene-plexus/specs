"""Pass a reduced-plan push to main only once the push before it has passed CI.

A reduced plan tests what changed since the previous push to main and trusts
that push's own run for the rest. A ship pushes merged work first and its pin
commit alone (P11), so without this the pin commit's run could pass, and Edge
publish it, while the full run of the work under it has failed or is still
running. The chain is transitive: the previous run passed only if its own
previous push had, back to a run that planned full coverage.

    python scripts/previous_push.py <previous commit>
"""

from __future__ import annotations

import re
import sys
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from edge_marker import api

SHA = re.compile(r"[a-f0-9]{40}")
POLL_SECONDS = 30
# GitHub lists a push's run within seconds; give it five minutes.
APPEAR_SECONDS = 5 * 60
WAIT_SECONDS = 55 * 60
Run = dict[str, Any]


def newest_run(commit: str) -> Run | None:
    """The newest CI run of a push of `commit` to main, as GitHub reports it now."""
    query = urlencode({"head_sha": commit, "event": "push", "branch": "main", "per_page": 100})
    body = api(f"actions/workflows/ci.yml/runs?{query}")
    runs = body.get("workflow_runs") if isinstance(body, dict) else None
    if not isinstance(runs, list):
        raise ValueError("GitHub did not return CI runs")
    matching = [
        entry
        for entry in runs
        if entry.get("head_sha") == commit
        and entry.get("event") == "push"
        and entry.get("head_branch") == "main"
    ]
    return max(matching, key=lambda entry: entry["id"], default=None)


def wait(
    commit: str,
    lookup: Callable[[str], Run | None] = newest_run,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[bool, str]:
    """Whether the previous push's CI passed, and the reason in one line."""
    started = clock()
    while True:
        run = lookup(commit)
        elapsed = clock() - started
        if run is None:
            if elapsed >= APPEAR_SECONDS:
                return False, f"No CI run of the previous push to main ({commit[:7]}) was found."
        elif run.get("status") == "completed":
            where = run.get("html_url", f"run {run.get('id')}")
            if run.get("conclusion") == "success":
                return True, f"The previous push to main ({commit[:7]}) passed CI: {where}"
            return False, (
                f"The previous push to main ({commit[:7]}) concluded "
                f"{run.get('conclusion')}: {where}. Re-run it, or push a fix, then re-run this job."
            )
        if elapsed >= WAIT_SECONDS:
            return False, (
                f"The previous push to main ({commit[:7]}) was still running after "
                f"{WAIT_SECONDS // 60} minutes; re-run this job once it finishes."
            )
        sleep(POLL_SECONDS)


def main() -> int:
    if len(sys.argv) != 2 or not SHA.fullmatch(sys.argv[1]) or sys.argv[1] == "0" * 40:
        print("usage: previous_push.py <the previous push's full commit ID>", file=sys.stderr)
        return 2
    passed, reason = wait(sys.argv[1])
    print(reason if passed else f"::error::{reason}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
