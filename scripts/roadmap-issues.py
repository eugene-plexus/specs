#!/usr/bin/env python3
"""One GitHub issue per roadmap row, with the row's brief, labels and status.

The data is docs/design/roadmap-rows.json (made from docs/design/roadmap.md).
The issue body is the brief in development-plan.md, Appendix B. The script
uses only the standard library and the `gh` CLI.

  python scripts/roadmap-issues.py --dry-run --show 1,11,53   # plan, touch nothing
  python scripts/roadmap-issues.py                            # create the missing issues
  python scripts/roadmap-issues.py --update                   # also rewrite the open ones

Rules:
- An issue belongs to a row when its title starts with `Row <n>:` and it has
  the `row` label. The script never touches any other issue.
- A plain run creates the missing issues and changes no existing one.
- `--update` rewrites the body and labels of existing OPEN row issues. It
  keeps three lines that the orchestrator fills in by hand ("Do not change",
  "Store migration number", "The test that must fail before the change"). It
  never reopens a closed issue and never edits one.
- The status label is `status:needs-design`, `status:blocked` or
  `status:ready`, chosen from the data. `--update` changes only those three.
  A row whose issue carries any other status (`building`, `review`, `green`)
  keeps it.
- Two passes: pass 1 creates the missing issues; pass 2 rewrites the bodies
  so the "needs" links name the issue numbers made in the same run.
- A real run writes `"issue": <number>` on each row in the data file.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parent.parent
ROWS_FILE = ROOT / "docs/design/roadmap-rows.json"
REPO = "eugene-plexus/specs"

LANES = ("OPS", "TRUST", "GW", "ENG", "WB", "LIB", "WEB", "AG2", "DESIGN")
RISKS = ("low", "cross", "high")
SIZES = ("S", "M", "L")
DESIGN_STATES = ("ready", "short", "full")
STATUSES = ("needs-design", "blocked", "ready", "building", "review", "green")
SETTABLE_STATUSES = ("status:needs-design", "status:blocked", "status:ready")

# One colour family per kind: lanes are blues, risks are reds, sizes are greys,
# design states are purples, statuses run from yellow through to green.
LABEL_TABLE: list[tuple[str, str, str]] = [
    ("row", "3E4B9E", "A roadmap row; its issue is the row's brief"),
    ("lane:OPS", "1D76DB", "Lane OPS: specs scripts, CI workflows, installers"),
    ("lane:TRUST", "0A3069", "Lane TRUST: control trust and keys, agent identity"),
    ("lane:GW", "0969DA", "Lane GW: gateway request path, client keys"),
    ("lane:ENG", "54AEFF", "Lane ENG: the agent's engine adapters"),
    ("lane:WB", "218BFF", "Lane WB: Workbench store and server"),
    ("lane:LIB", "0550AE", "Lane LIB: the library"),
    ("lane:WEB", "80CCFF", "Lane WEB: console and Workbench web pages"),
    ("lane:AG2", "316DCA", "Lane AG2: agent apps, tray and folders; site-host"),
    ("lane:DESIGN", "B6E3FF", "Lane DESIGN: designs in docs/design"),
    ("risk:low", "F9D0C4", "Low risk: changed-file tests are enough"),
    ("risk:cross", "E99695", "Cross-component: needs branch integration"),
    ("risk:high", "B60205", "High risk: acceptance in CI and an adversarial review"),
    ("size:S", "EDEDED", "Under a day"),
    ("size:M", "D4D4D4", "One slice"),
    ("size:L", "BDBDBD", "Several slices"),
    ("design:ready", "E4D9F7", "The design is ready"),
    ("design:short", "D4C5F9", "A short design comes first"),
    ("design:full", "B59DEB", "A full design comes first"),
    ("status:needs-design", "FBCA04", "Waiting for its design"),
    ("status:blocked", "E99C0B", "Waiting for rows it needs"),
    ("status:ready", "C2E0C6", "Brief written; a builder can start"),
    ("status:building", "7CC38A", "A builder has it"),
    ("status:review", "3FA65E", "CI is running and a reviewer is reading"),
    ("status:green", "0E8A16", "CI is green; waiting for the orchestrator's merge"),
]
LABEL_BY_NAME = {name: (colour, description) for name, colour, description in LABEL_TABLE}
FAMILIES = ("lane:", "risk:", "size:", "design:")

DO_NOT_CHANGE = (
    "files that other lanes' in-progress rows own "
    "(the orchestrator fills this in when the row starts)"
)
MIGRATION = "assigned by the orchestrator when the row starts"
FAILING_TEST = "(the orchestrator fills this in when the row starts)"
PRESERVED = {
    "Do not change": DO_NOT_CHANGE,
    "Store migration number (Workbench only)": MIGRATION,
    "The test that must fail before the change": FAILING_TEST,
}
MARKER = "<!-- Made by scripts/roadmap-issues.py from docs/design/roadmap-rows.json. -->"
TITLE_PATTERN = re.compile(r"^Row (\d+): ")
YAML_TOKEN = re.compile(r"^[\w./-]+\.yaml\??$")


# --- pure parts -------------------------------------------------------------


def size_letter(size: str) -> str:
    """The largest of the letters in a size such as "S-M each" or "S, then L"."""
    letters = re.findall(r"\b[SML]\b", size)
    if not letters:
        raise ValueError(f"unreadable size {size!r}")
    return max(letters, key=SIZES.index)


def row_title(row: dict[str, Any]) -> str:
    return f"Row {row['row']}: {row['title']}"


def parse_row_number(title: str) -> int | None:
    match = TITLE_PATTERN.match(title)
    return int(match.group(1)) if match else None


def core_labels(row: dict[str, Any]) -> list[str]:
    """The labels that follow the data: row, lane, risk, size and design."""
    if row["lane"] not in LANES:
        raise ValueError(f"row {row['row']}: unknown lane {row['lane']!r}")
    if row["risk"] not in RISKS:
        raise ValueError(f"row {row['row']}: unknown risk {row['risk']!r}")
    if row["design_state"] not in DESIGN_STATES:
        raise ValueError(f"row {row['row']}: unknown design state {row['design_state']!r}")
    return [
        "row",
        f"lane:{row['lane']}",
        f"risk:{row['risk']}",
        f"size:{size_letter(row['size'])}",
        f"design:{row['design_state']}",
    ]


def choose_status(row: dict[str, Any], closed_rows: set[int]) -> str:
    """needs-design if a design comes first; else blocked while a needed row is open."""
    if row["design_state"] in ("short", "full"):
        return "status:needs-design"
    if any(needed not in closed_rows for needed in row["needs"]):
        return "status:blocked"
    return "status:ready"


def reconcile_labels(
    current: set[str], row: dict[str, Any], closed_rows: set[int]
) -> tuple[list[str], list[str]]:
    """Labels to add and to remove on an existing issue.

    Only the row, lane, risk, size and design labels and the three settable
    statuses are ever changed. Labels outside those are left alone, and so is
    a status beyond the three (building, review, green).
    """
    wanted = set(core_labels(row))
    locked = {label for label in current if label.startswith("status:")} - set(SETTABLE_STATUSES)
    if locked:
        managed_statuses: set[str] = set()
    else:
        wanted.add(choose_status(row, closed_rows))
        managed_statuses = set(SETTABLE_STATUSES)
    managed = {name for name in LABEL_BY_NAME if name.startswith(FAMILIES)} | managed_statuses
    add = sorted(wanted - current)
    remove = sorted((current & managed) - wanted)
    return add, remove


def contract_text(contract: str) -> str:
    text = contract.strip()
    if not text:
        return "none"
    if text == "?":
        return "not known yet (the design decides)"
    tokens = text.split()
    if all(YAML_TOKEN.match(token) for token in tokens):
        return ", ".join(
            f"`openapi/{token.rstrip('?')}`" + (" (possibly)" if token.endswith("?") else "")
            for token in tokens
        )
    return text


def risk_text(row: dict[str, Any]) -> str:
    risk, note = row["risk"], row["risk_note"].strip()
    if note == risk:
        return risk
    if note.startswith(risk):
        return note
    return f"{risk} (roadmap says: {note})"


def what_it_is(row: dict[str, Any]) -> str:
    """The summary without the title it starts with."""
    summary = row["summary"].strip()
    prefix = row["title"] + "."
    if summary.startswith(prefix) and summary[len(prefix) :].strip():
        return summary[len(prefix) :].strip()
    return summary


def needs_text(row: dict[str, Any], numbers: dict[int, int]) -> str:
    if not row["needs"]:
        return "none"
    parts = [
        f"{needed} (#{numbers[needed]})" if needed in numbers else f"{needed} (issue pending)"
        for needed in row["needs"]
    ]
    return ("rows " if len(parts) > 1 else "row ") + ", ".join(parts)


def design_text(row: dict[str, Any], repo: str) -> str:
    base = f"https://github.com/{repo}/blob/main/docs/design/"
    state = {
        "ready": "ready.",
        "short": "a short design comes first.",
        "full": "a full design comes first.",
    }[row["design_state"]]
    docs = ", ".join(f"[{name}]({base}{name})" for name in row["design_docs"]) or "none yet"
    return f"{state} Docs: {docs}."


def calls_text(row: dict[str, Any]) -> str:
    if not row["calls"]:
        return "none."
    return (
        ", ".join(row["calls"])
        + ". Builders build the recommended option until Troy answers (development plan, P4)."
        " Each call and its recommended option are in `docs/private/calls.md` in the main"
        " checkout; the orchestrator adds them here when the row starts."
    )


def render_body(
    row: dict[str, Any],
    lanes: dict[str, list[int]],
    numbers: dict[int, int],
    *,
    repo: str = REPO,
    preserved: dict[str, str] | None = None,
) -> str:
    """The brief of development-plan.md Appendix B, filled from the row."""
    preserved = preserved or {}
    queue = lanes.get(row["lane"], [])
    position = queue.index(row["row"]) + 1 if row["row"] in queue else row["lane_order"]
    lane = f"{row['lane']}, position {position}" + (f" of {len(queue)}" if queue else "")
    roadmap = f"https://github.com/{repo}/blob/main/docs/design/roadmap.md"
    repos = ", ".join(f"`{name}`" for name in row["repos"]) or "none"
    files = "\n".join(f"- `{path}`" for path in row["hot_files"]) or (
        "- not known yet; the row's design names them"
    )

    def filled(key: str) -> str:
        value = preserved.get(key, "").strip()
        return value if value and value != PRESERVED[key] else PRESERVED[key]

    if row["contract"].strip() == "design only":
        first = f"The design is written in docs/design and names its calls: {what_it_is(row)}"
    else:
        first = f"What the summary says is true, and a test or a CI run shows it: {what_it_is(row)}"
    done = [
        first,
        "CI green in every repository; branch integration green if two or more repositories change",
    ]
    if row["risk"] == "high":
        done.append("The reviewer's findings answered")

    lines = [
        f"**Row:** {row['row']}, {row['title']} ([roadmap.md]({roadmap}), part {row['part']})",
        "",
        f"**Lane:** {lane} | **Risk:** {risk_text(row)} | **Size:** {row['size']}",
        "",
        f"**Needs (merged first):** {needs_text(row, numbers)}",
        "",
        f"**Design:** {design_text(row, repo)}",
        "",
        f"**Open calls and the default to build:** {calls_text(row)}",
        "",
        f"**Repositories:** {repos} | **Contract:** {contract_text(row['contract'])}",
        "",
        "**Files you will likely change:**",
        "",
        files,
        "",
        f"**Do not change:** {filled('Do not change')}",
        "",
    ]
    if row["lane"] == "WB":
        lines += [
            f"**Store migration number (Workbench only):** "
            f"{filled('Store migration number (Workbench only)')}",
            "",
        ]
    lines += [
        f"**The test that must fail before the change:** "
        f"{filled('The test that must fail before the change')}",
        "",
        "**Done when:**",
        "",
        *[f"- {item}" for item in done],
        "",
        "## What it is",
        "",
        what_it_is(row),
        "",
        f"Comes from: {row['from']}. Helps: {row['who']}.",
        "",
        "## Why here, and what it needs",
        "",
        row["notes"].strip() or "Nothing more than the lines above.",
        "",
        MARKER,
    ]
    return "\n".join(lines) + "\n"


def extract_preserved(body: str) -> dict[str, str]:
    """The values of the three hand-filled lines, when a person changed them."""
    found: dict[str, list[str]] = {}
    key: str | None = None
    for line in body.replace("\r\n", "\n").split("\n"):
        match = re.match(r"^\*\*(.+?):\*\*(.*)$", line)
        if match:
            key = match.group(1) if match.group(1) in PRESERVED else None
            if key:
                found[key] = [match.group(2)]
        elif line.startswith("## ") or line.startswith("<!--"):
            key = None
        elif key:
            found[key].append(line)
    values = {name: "\n".join(parts).strip() for name, parts in found.items()}
    return {name: value for name, value in values.items() if value and value != PRESERVED[name]}


def same_text(left: str, right: str) -> bool:
    def normal(text: str) -> str:
        return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).strip()

    return normal(left) == normal(right)


# --- the gh CLI -------------------------------------------------------------


class Tracker(Protocol):
    def labels(self) -> dict[str, tuple[str, str]]: ...
    def put_label(self, name: str, colour: str, description: str) -> None: ...
    def row_issues(self) -> list[dict[str, Any]]: ...
    def next_number(self) -> int: ...
    def create_issue(self, title: str, body: str, labels: list[str]) -> int: ...
    def edit_issue(
        self,
        number: int,
        *,
        title: str | None,
        body: str | None,
        add: list[str],
        remove: list[str],
    ) -> None: ...


class Gh:
    """The Tracker over the `gh` CLI."""

    def __init__(self, repo: str, pause: float = 1.0) -> None:
        self.repo = repo
        self.pause = pause

    def _run(self, args: list[str], stdin: str | None = None, write: bool = False) -> str:
        for attempt in range(6):
            done = subprocess.run(
                ["gh", *args],
                input=stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if done.returncode == 0:
                if write:
                    time.sleep(self.pause)
                return done.stdout
            message = done.stderr.strip()
            if re.search(r"rate limit|secondary|abuse|HTTP 5\d\d", message, re.I) and attempt < 5:
                time.sleep(30 * (attempt + 1))
                continue
            raise RuntimeError(f"gh {' '.join(args[:3])} failed: {message}")
        raise RuntimeError("unreachable")

    def labels(self) -> dict[str, tuple[str, str]]:
        out = self._run(
            [
                "label",
                "list",
                "--repo",
                self.repo,
                "--limit",
                "500",
                "--json",
                "name,color,description",
            ]
        )
        return {
            item["name"]: (item["color"].upper(), item.get("description") or "")
            for item in json.loads(out)
        }

    def put_label(self, name: str, colour: str, description: str) -> None:
        self._run(
            [
                "label",
                "create",
                name,
                "--repo",
                self.repo,
                "--color",
                colour,
                "--description",
                description,
                "--force",
            ],
            write=True,
        )

    def row_issues(self) -> list[dict[str, Any]]:
        out = self._run(
            [
                "issue",
                "list",
                "--repo",
                self.repo,
                "--label",
                "row",
                "--state",
                "all",
                "--limit",
                "1000",
                "--json",
                "number,title,state,body,labels",
            ]
        )
        issues = json.loads(out)
        for issue in issues:
            issue["labels"] = [label["name"] for label in issue["labels"]]
        return issues

    def next_number(self) -> int:
        out = self._run(
            [
                "api",
                f"repos/{self.repo}/issues?state=all&per_page=1&sort=created&direction=desc",
                "--jq",
                ".[0].number // 0",
            ]
        )
        return int(out.strip() or 0) + 1

    def create_issue(self, title: str, body: str, labels: list[str]) -> int:
        args = ["issue", "create", "--repo", self.repo, "--title", title, "--body-file", "-"]
        for label in labels:
            args += ["--label", label]
        out = self._run(args, stdin=body, write=True)
        match = re.search(r"/issues/(\d+)\s*$", out.strip())
        if not match:
            raise RuntimeError(f"gh issue create gave no issue URL: {out!r}")
        return int(match.group(1))

    def edit_issue(
        self,
        number: int,
        *,
        title: str | None,
        body: str | None,
        add: list[str],
        remove: list[str],
    ) -> None:
        args = ["issue", "edit", str(number), "--repo", self.repo]
        if title is not None:
            args += ["--title", title]
        if body is not None:
            args += ["--body-file", "-"]
        for label in add:
            args += ["--add-label", label]
        for label in remove:
            args += ["--remove-label", label]
        self._run(args, stdin=body, write=True)


# --- the run ----------------------------------------------------------------


def check_data(doc: dict[str, Any]) -> None:
    rows = doc["rows"]
    numbers = [row["row"] for row in rows]
    if len(set(numbers)) != len(numbers):
        raise ValueError("the data file lists a row twice")
    for row in rows:
        core_labels(row)
        for needed in row["needs"]:
            if needed not in numbers:
                raise ValueError(f"row {row['row']} needs row {needed}, which is not in the data")


def ensure_labels(tracker: Tracker, dry_run: bool, out: Any) -> int:
    live = tracker.labels()
    changed = 0
    for name, colour, description in LABEL_TABLE:
        if live.get(name) == (colour, description):
            continue
        changed += 1
        verb = "update" if name in live else "create"
        out(f"{'would ' if dry_run else ''}{verb} label {name}")
        if not dry_run:
            tracker.put_label(name, colour, description)
    return changed


def run(
    doc: dict[str, Any],
    tracker: Tracker,
    *,
    update: bool = False,
    dry_run: bool = False,
    show: set[int] | None = None,
    repo: str = REPO,
    out: Any = print,
) -> dict[str, Any]:
    """Create the missing row issues (pass 1), then fix their links (pass 2)."""
    show = show or set()
    check_data(doc)
    rows = sorted(doc["rows"], key=lambda row: row["row"])
    by_row = {row["row"]: row for row in rows}
    lanes = doc["lanes"]
    tally = {"created": 0, "updated": 0, "unchanged": 0, "closed": 0, "labels": 0}

    tally["labels"] = ensure_labels(tracker, dry_run, out)

    existing: dict[int, dict[str, Any]] = {}
    for issue in sorted(tracker.row_issues(), key=lambda item: item["number"]):
        number = parse_row_number(issue["title"])
        if number is None:
            out(
                f"warning: #{issue['number']} has the row label but no `Row <n>:` title; left alone"
            )
        elif number in existing:
            out(
                f"warning: #{issue['number']} repeats row {number} (#{existing[number]['number']}); left alone"
            )
        elif number not in by_row:
            out(
                f"warning: #{issue['number']} is for row {number}, which is not in the data; left alone"
            )
        else:
            existing[number] = issue

    numbers = {n: issue["number"] for n, issue in existing.items()}
    closed = {n for n, issue in existing.items() if issue["state"].upper() == "CLOSED"}

    # Pass 1: create what is missing.
    made: dict[int, tuple[str, list[str]]] = {}  # row -> (body as created, labels)
    missing = [row for row in rows if row["row"] not in existing]
    predicted = tracker.next_number() if dry_run and missing else 0
    for row in missing:
        n = row["row"]
        labels = core_labels(row) + [choose_status(row, closed)]
        if dry_run:
            numbers[n] = predicted
            predicted += 1
            made[n] = ("", labels)
        else:
            body = render_body(row, lanes, numbers, repo=repo)
            numbers[n] = tracker.create_issue(row_title(row), body, labels)
            made[n] = (body, labels)
        tally["created"] += 1
        out(
            f"{'would create' if dry_run else 'created'} #{numbers[n]} {row_title(row)} [{', '.join(labels)}]"
        )

    # Pass 2: every body now knows every issue number.
    for row in rows:
        n = row["row"]
        if n in made:
            old_body, labels_now = made[n]
            current = set(labels_now)
            preserved: dict[str, str] = {}
            old_title = row_title(row)
        elif update and n in existing and n not in closed:
            issue = existing[n]
            old_body, current = issue["body"] or "", set(issue["labels"])
            preserved = extract_preserved(old_body)
            old_title = issue["title"]
        else:
            if update and n in closed:
                tally["closed"] += 1
                out(f"#{numbers[n]} row {n}: closed, left alone")
            continue
        body = render_body(row, lanes, numbers, repo=repo, preserved=preserved)
        if n in show:
            out(f"----- #{numbers[n]} {row_title(row)} -----\n{body}-----")
        if n in made:
            if dry_run or same_text(old_body, body):
                continue
            add, remove = [], []
        else:
            add, remove = reconcile_labels(current, row, closed)
        title = row_title(row)
        changes = []
        if not same_text(old_body, body):
            changes.append("body")
        if add or remove:
            changes.append("labels +" + ",".join(add) + " -" + ",".join(remove))
        if old_title != title:
            changes.append("title")
        if not changes:
            tally["unchanged"] += 1
            out(f"#{numbers[n]} row {n}: unchanged")
            continue
        out(
            f"{'would update' if dry_run else 'updated'} #{numbers[n]} row {n}: {'; '.join(changes)}"
        )
        tally["updated"] += 1
        if not dry_run:
            tracker.edit_issue(
                numbers[n],
                title=title if old_title != title else None,
                body=body if not same_text(old_body, body) else None,
                add=add,
                remove=remove,
            )

    out(
        "{} created, {} updated, {} unchanged, {} closed left alone, {} labels {}".format(
            tally["created"],
            tally["updated"],
            tally["unchanged"],
            tally["closed"],
            tally["labels"],
            "to change" if dry_run else "changed",
        )
    )
    return {"numbers": numbers, "tally": tally}


def write_numbers(path: Path, doc: dict[str, Any], numbers: dict[int, int]) -> bool:
    """Write `"issue": <number>` on each row; True when the file changed."""
    for row in doc["rows"]:
        if row["row"] in numbers:
            row["issue"] = numbers[row["row"]]
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--rows-file", type=Path, default=ROWS_FILE)
    parser.add_argument("--update", action="store_true", help="rewrite the open row issues")
    parser.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    parser.add_argument("--show", default="", help="rows whose full body is printed, e.g. 1,11,53")
    parser.add_argument("--pause", type=float, default=1.0, help="seconds between writes")
    arguments = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    doc = json.loads(arguments.rows_file.read_text(encoding="utf-8"))
    show = {int(part) for part in arguments.show.split(",") if part.strip()}
    result = run(
        doc,
        Gh(arguments.repo, arguments.pause),
        update=arguments.update,
        dry_run=arguments.dry_run,
        show=show,
        repo=arguments.repo,
    )
    if not arguments.dry_run:
        if write_numbers(arguments.rows_file, doc, result["numbers"]):
            print(f"wrote the issue numbers to {arguments.rows_file}")
        else:
            print("the issue numbers in the data file are already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
