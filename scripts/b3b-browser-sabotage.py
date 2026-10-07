"""Sabotage for `b3b-browser-check.py`: each entry puts one rule of 2b.3b back
in a copy of what ships (Workbench's `dist` commit, or the site host's commit),
runs the browser check against that copy, and names the steps that must FAIL.
Copies are made from `git archive`, so the checkouts are never touched.

The run of record (the check against the unchanged commits, all passing) is
the baseline; it is not run again here (CLAUDE.md: one run of record).

Usage: python specs/scripts/b3b-browser-sabotage.py --workbench ce2103f
       [--site-host 26a4f0f] [--label TEXT ...]
"""

from __future__ import annotations

import argparse
import io
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPOS = HERE.parents[1]
CHECK = HERE / "b3b-browser-check.py"
PYTHON = REPOS / "agent" / ".venv" / "Scripts" / "python.exe"

WB_TOOLS = "src/eugene_plexus_workbench/tools.py"
WB_ANSWERS = "src/eugene_plexus_workbench/answers.py"
SH_HOST = "src/eugene_plexus_site_host/host.py"

#: (label, repo, file, the text as it ships, the text sabotaged, steps that must fail)
SABOTAGES: list[tuple[str, str, str, str, str, set[str]]] = [
    ("a call the rules allow is asked about anyway", "workbench", WB_TOOLS,
     'ask = arguments.get("folder") in rule', "ask = True", {"W1", "W4"}),
    ("a call the rules ask about runs without asking", "workbench", WB_TOOLS,
     'ask = arguments.get("folder") in rule', "ask = False", {"W2a", "W2b", "W2c"}),
    ("Workbench never tells the site the person was asked (J72)", "workbench", WB_TOOLS,
     'asked=bool(call.get("ask")) and bool(call.get("rules")),', "asked=False,", {"W2a"}),
    ("Stop does not end the answer", "workbench", WB_ANSWERS,
     "running.task.cancel()\n        with contextlib.suppress",
     "pass\n        with contextlib.suppress", {"W2c", "W5"}),
    # Where "deny" is decided: the person's offer. (The listing's own filter
    # after it, `target.allowed`, is a second guard: sabotaged alone, it
    # escapes, since what it would drop was never offered.)
    ("the site offers a change tool its rules deny", "site-host", SH_HOST,
     'writable = [n for n in folders if rules[n]["change"] != "deny"]',
     "writable = list(folders)", {"W3"}),
]


def extract(repo: str, commit: str, into: Path) -> Path:
    data = subprocess.run(["git", "-C", str(REPOS / repo), "archive", commit], check=True,
                          capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(into, filter="data")
    return into


def sabotage(tree: Path, file: str, old: str, new: str) -> None:
    path = tree / file
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{file}: the text to sabotage occurs {count} times, not once: {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbench", required=True, help="the Workbench dist commit")
    parser.add_argument("--site-host", default="HEAD", help="the site host commit")
    parser.add_argument("--label", action="append", default=[])
    args = parser.parse_args()
    chosen = [s for s in SABOTAGES if not args.label or any(t in s[0] for t in args.label)]
    caught = 0
    for label, repo, file, old, new, must_fail in chosen:
        work = Path(tempfile.mkdtemp(prefix="ep-b3b-sabotage-"))
        try:
            workbench = extract("workbench", args.workbench, work / "workbench")
            site_host = extract("site-host", args.site_host, work / "site-host")
            sabotage(workbench if repo == "workbench" else site_host, file, old, new)
            print(f"\n== {label} ({repo}: {file})", flush=True)
            done = subprocess.run(
                [str(PYTHON), str(CHECK), "--workbench-source", str(workbench),
                 "--site-host-source", str(site_host)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=1800,
            )
            failed = set(re.findall(r"^\s+FAIL\s+(\w+)\.", done.stdout, re.MULTILINE))
            passed = set(re.findall(r"^\s+PASS\s+(\w+)\.", done.stdout, re.MULTILINE))
            missing = must_fail - failed
            if missing:
                print(f"ESCAPED: {sorted(missing)} did not fail (failed: {sorted(failed)})", flush=True)
                print(done.stdout[-3000:] + done.stderr[-1500:], flush=True)
            else:
                caught += 1
                others = failed - must_fail
                print(f"CAUGHT by {sorted(must_fail)}" +
                      (f"; also failed: {sorted(others)}" if others else "") +
                      f"; passed: {sorted(passed)}", flush=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    print(f"\n{caught}/{len(chosen)} caught", flush=True)
    return 0 if caught == len(chosen) else 1


if __name__ == "__main__":
    sys.exit(main())
