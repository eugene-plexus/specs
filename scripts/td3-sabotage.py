"""Sabotage pass for tool-driver#3 (pacing, one retry, quota vs too fast).

Each sabotage is a plausible breakage of the change. For each: copy the
file aside, apply the breakage, run the relevant tests, record caught or
escaped, and RESTORE FROM THE COPY (never `git checkout --`, which would
revert the uncommitted change under test). Opens and closes with a
baseline run that must pass.
"""

from __future__ import annotations

import shutil
import tempfile
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2] / "tool-driver"
SRC = REPO / "src" / "eugene_plexus_tool_driver"
PY = next(
    (p for p in (REPO / ".venv/Scripts/python.exe", REPO / ".venv/bin/python") if p.exists()),
    REPO / ".venv/Scripts/python.exe",
)
# The byte copies live outside every checkout.
BACKUP = Path(tempfile.gettempdir()) / "ep-td3-sabotage-originals"
TESTS = ["tests/test_web_search.py", "tests/test_settings_truth.py"]

SABOTAGES: list[tuple[str, str, str, str]] = [
    (
        "remove the lock",
        "pacing.py",
        "        async with self._lock:\n",
        "        if True:\n",
    ),
    (
        "drop the retry",
        "service.py",
        "                if not failure.worth_a_retry:\n                    raise\n",
        "                if True:\n                    raise\n",
    ),
    (
        "retry twice",
        "service.py",
        "            except SearchFailure as again:\n",
        "            except SearchFailure as again:\n"
        "                if again.worth_a_retry:\n"
        "                    return await provider.search(\n"
        "                        client, account, self._with_time_left(query, deadline)\n"
        "                    )\n",
    ),
    (
        "retry a quota 429",
        "providers.py",
        "            retry_after=resets_in,\n        )\n",
        "            retry_after=resets_in,\n            worth_a_retry=True,\n        )\n",
    ),
    (
        "ignore the timeout bound",
        "service.py",
        "                if self._clock() + wait + took >= deadline:\n",
        "                if False:\n",
    ),
    (
        "no room left for the retry's answer",
        "service.py",
        "                if self._clock() + wait + took >= deadline:\n",
        "                if self._clock() + wait >= deadline:\n",
    ),
    (
        "the retry gets a fresh full timeout",
        "service.py",
        "        return dataclasses.replace(query, timeout=deadline - self._clock())\n",
        "        return query\n",
    ),
    (
        "pace SearXNG by default",
        "providers.py",
        '        search=search_searxng,\n        billing="free",\n',
        '        search=search_searxng,\n        billing="free",\n        search_interval=1.0,\n',
    ),
    (
        "do not pace Brave by default",
        "providers.py",
        "        search_interval=1.0,\n",
        "        search_interval=0.0,\n",
    ),
    (
        "space from the request, not the answer",
        "pacing.py",
        "            if gap > 0:\n"
        "                await self._sleep(gap)\n"
        "            try:\n"
        "                yield\n"
        "            finally:\n"
        "                self._last = self._clock()\n",
        "            if gap > 0:\n"
        "                await self._sleep(gap)\n"
        "            self._last = self._clock()\n"
        "            yield\n",
    ),
    (
        "an unpaced answer does not count for the next gap",
        "pacing.py",
        "        if interval <= 0:\n"
        "            try:\n"
        "                yield\n"
        "            finally:\n"
        "                self._last = self._clock()\n"
        "            return\n",
        "        if interval <= 0:\n            yield\n            return\n",
    ),
    (
        "the pacer sends a turn past the deadline",
        "pacing.py",
        "            if self._clock() + max(gap, 0.0) >= deadline:\n",
        "            if False:\n",
    ),
    (
        "an operator's 0 read as unset",
        "service.py",
        "        interval = provider.search_interval if configured is None else float(configured)\n",
        "        interval = float(configured or provider.search_interval)\n",
    ),
    (
        "ignore Retry-After",
        "providers.py",
        "    retry_after = _retry_after(response)\n    used_up",
        "    retry_after = None\n    used_up",
    ),
    (
        "ignore X-RateLimit-Reset for the wait",
        "providers.py",
        "    waits = [w for w in (retry_after, reset[0] if reset is not None else None) if w is not None]\n",
        "    waits = [w for w in (retry_after,) if w is not None]\n",
    ),
    (
        "take the shorter of the two waits",
        "providers.py",
        "        retry_after=max(waits) if waits else None,\n",
        "        retry_after=min(waits) if waits else None,\n",
    ),
    (
        "the retry may wait less than the interval",
        "service.py",
        "                wait = max(failure.retry_after or 0.0, interval)\n",
        "                wait = failure.retry_after if failure.retry_after is not None else interval\n",
    ),
    (
        "quota read off the first (per-second) window too",
        "providers.py",
        "if i > 0 and left == 0]",
        "if left == 0]",
    ),
    (
        "a malformed header raises",
        "providers.py",
        "    try:\n"
        '        numbers = [float(part) for part in value.split(",")]\n'
        "    except ValueError:\n"
        "        return None\n",
        '    numbers = [float(part) for part in value.split(",")]\n',
    ),
    (
        "negative and non-finite numbers believed",
        "providers.py",
        "    if not all(math.isfinite(n) and n >= 0 for n in numbers):\n        return None\n",
        "",
    ),
    (
        "windows that disagree are paired anyway",
        "providers.py",
        "        remaining = reset = None\n",
        "        pass\n",
    ),
    (
        "SearXNG's limiter retried too",
        "providers.py",
        "            retry_after=_retry_after(response),\n        )\n",
        "            retry_after=_retry_after(response),\n            worth_a_retry=True,\n        )\n",
    ),
    (
        "the second failure does not say it was a retry",
        "service.py",
        "                again.detail = (\n"
        "                    f\"{again.detail.rstrip('.')}. It was tried once more after {wait:g}s.\"\n"
        "                )\n",
        "",
    ),
    (
        "unset Brave interval reported as 0",
        "config.py",
        '        return {"unsetMeans": means, "unsetResolvesTo": interval}\n',
        '        return {"unsetMeans": means, "unsetResolvesTo": 0.0}\n',
    ),
    (
        "the quota message loses its reset",
        "providers.py",
        "            count = round(seconds / size)\n",
        "            count = int(seconds)\n",
    ),
]


def run_tests() -> tuple[str, str]:
    try:
        result = subprocess.run(
            [str(PY), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return "hung", "timed out after 300s"
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    summary = lines[-1] if lines else result.stderr.strip()[-200:]
    failed = [line for line in lines if line.startswith(("FAILED", "ERROR"))]
    if failed:
        summary = f"{summary}\n           {failed[0][:150]}"
    return ("passed" if result.returncode == 0 else "failed"), summary


def main() -> int:
    BACKUP.mkdir(exist_ok=True)
    outcome, summary = run_tests()
    print(f"baseline: {outcome} -- {summary}")
    if outcome != "passed":
        print("baseline must pass; stopping")
        return 2

    caught = escaped = 0
    for name, file, old, new in SABOTAGES:
        path = SRC / file
        copy = BACKUP / file
        shutil.copy2(path, copy)
        original = path.read_bytes()
        text = original.decode("utf-8")
        count = text.count(old)
        if count != 1 or old == new:
            print(f"BAD SABOTAGE ({count} matches): {name}")
            return 3
        try:
            path.write_bytes(text.replace(old, new).encode("utf-8"))
            outcome, summary = run_tests()
        finally:
            shutil.copy2(copy, path)
        if path.read_bytes() != original:
            print(f"RESTORE FAILED for {file}; stopping")
            return 4
        if outcome == "passed":
            escaped += 1
            print(f"ESCAPED  {name}  [{file}] -- {summary}")
        else:
            caught += 1
            print(f"caught   {name}  [{file}] -- {summary}")

    outcome, summary = run_tests()
    print(f"closing baseline: {outcome} -- {summary}")
    print(f"\n{caught} caught, {escaped} escaped, of {len(SABOTAGES)}")
    return 0 if escaped == 0 and outcome == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
