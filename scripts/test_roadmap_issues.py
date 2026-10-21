from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any

_spec = importlib.util.spec_from_file_location(
    "roadmap_issues", Path(__file__).with_name("roadmap-issues.py")
)
roadmap_issues = importlib.util.module_from_spec(_spec)
sys.modules["roadmap_issues"] = roadmap_issues
_spec.loader.exec_module(roadmap_issues)  # type: ignore[union-attr]

ROWS_FILE = Path(__file__).resolve().parent.parent / "docs/design/roadmap-rows.json"


def make_row(number: int, **changes: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "row": number,
        "part": 1,
        "title": f"Title {number}",
        "summary": f"Title {number}. It does a thing people can see",
        "from": "SRC-1",
        "size": "M",
        "risk": "cross",
        "risk_note": "cross",
        "who": "everyone",
        "notes": "Because it is first",
        "lane": "GW",
        "lane_order": 1,
        "repos": ["gateway", "specs"],
        "contract": "gateway.yaml control.yaml?",
        "hot_files": ["gateway/src/a.py"],
        "design_state": "ready",
        "needs": [],
        "design_docs": ["doc-a.md"],
        "calls": [],
    }
    row.update(changes)
    return row


class FakeTracker:
    """An in-memory repo: labels and issues, with a count of the writes."""

    def __init__(self, other_issues: list[dict[str, Any]] | None = None) -> None:
        self.live_labels: dict[str, tuple[str, str]] = {}
        self.issues: dict[int, dict[str, Any]] = {}
        self.counter = 20
        self.writes = 0
        for issue in other_issues or []:
            self.issues[issue["number"]] = deepcopy(issue)
            self.counter = max(self.counter, issue["number"])

    def labels(self) -> dict[str, tuple[str, str]]:
        return dict(self.live_labels)

    def put_label(self, name: str, colour: str, description: str) -> None:
        self.writes += 1
        self.live_labels[name] = (colour, description)

    def row_issues(self) -> list[dict[str, Any]]:
        return [deepcopy(issue) for issue in self.issues.values() if "row" in issue["labels"]]

    def next_number(self) -> int:
        return self.counter + 1

    def create_issue(self, title: str, body: str, labels: list[str]) -> int:
        self.writes += 1
        self.counter += 1
        self.issues[self.counter] = {
            "number": self.counter,
            "title": title,
            "body": body,
            "state": "OPEN",
            "labels": list(labels),
        }
        return self.counter

    def edit_issue(
        self,
        number: int,
        *,
        title: str | None,
        body: str | None,
        add: list[str],
        remove: list[str],
    ) -> None:
        self.writes += 1
        issue = self.issues[number]
        if title is not None:
            issue["title"] = title
        if body is not None:
            issue["body"] = body
        issue["labels"] = sorted((set(issue["labels"]) | set(add)) - set(remove))


def quiet(_: str) -> None:
    return None


class SizeTests(unittest.TestCase):
    def test_compound_sizes_map_to_the_larger_letter(self) -> None:
        cases = {
            "S": "S",
            "M": "M",
            "L": "L",
            "S-M": "M",
            "M-L": "L",
            "S-M each": "M",
            "M each": "M",
            "S+M": "M",
            "S, then L": "L",
            "L, S each": "L",
        }
        for raw, letter in cases.items():
            with self.subTest(size=raw):
                self.assertEqual(roadmap_issues.size_letter(raw), letter)

    def test_unreadable_size_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            roadmap_issues.size_letter("big")


class LabelTests(unittest.TestCase):
    def test_core_labels_follow_the_data(self) -> None:
        row = make_row(4, lane="TRUST", risk="high", size="S-M", design_state="short")
        self.assertEqual(
            roadmap_issues.core_labels(row),
            ["row", "lane:TRUST", "risk:high", "size:M", "design:short"],
        )

    def test_unknown_lane_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            roadmap_issues.core_labels(make_row(4, lane="NOPE"))

    def test_every_label_in_the_table_exists_once(self) -> None:
        names = [name for name, _, _ in roadmap_issues.LABEL_TABLE]
        self.assertEqual(len(names), len(set(names)))
        for lane in roadmap_issues.LANES:
            self.assertIn(f"lane:{lane}", names)
        for status in roadmap_issues.STATUSES:
            self.assertIn(f"status:{status}", names)
        for _, colour, description in roadmap_issues.LABEL_TABLE:
            self.assertRegex(colour, "^[0-9A-F]{6}$")
            self.assertLessEqual(len(description), 100)

    def test_status_choice(self) -> None:
        for state in ("short", "full"):
            row = make_row(1, design_state=state, needs=[2])
            self.assertEqual(roadmap_issues.choose_status(row, set()), "status:needs-design")
        waiting = make_row(1, needs=[2, 3])
        self.assertEqual(roadmap_issues.choose_status(waiting, {2}), "status:blocked")
        self.assertEqual(roadmap_issues.choose_status(waiting, {2, 3}), "status:ready")
        self.assertEqual(roadmap_issues.choose_status(make_row(1), set()), "status:ready")

    def test_reconcile_changes_only_what_it_owns(self) -> None:
        row = make_row(1, lane="LIB", needs=[2])
        current = {
            "row",
            "lane:GW",
            "risk:cross",
            "size:M",
            "design:ready",
            "status:ready",
            "good first issue",
        }
        add, remove = roadmap_issues.reconcile_labels(current, row, set())
        self.assertEqual(add, ["lane:LIB", "status:blocked"])
        self.assertEqual(remove, ["lane:GW", "status:ready"])

    def test_reconcile_keeps_a_status_beyond_the_three(self) -> None:
        row = make_row(1, needs=[2])
        for kept in ("status:building", "status:review", "status:green"):
            with self.subTest(status=kept):
                current = set(roadmap_issues.core_labels(row)) | {kept, "status:ready"}
                add, remove = roadmap_issues.reconcile_labels(current, row, set())
                self.assertEqual((add, remove), ([], []))

    def test_reconcile_needs_no_change_when_labels_match(self) -> None:
        row = make_row(1)
        current = set(roadmap_issues.core_labels(row)) | {"status:ready"}
        self.assertEqual(roadmap_issues.reconcile_labels(current, row, set()), ([], []))


class TitleTests(unittest.TestCase):
    def test_row_number_from_title(self) -> None:
        self.assertEqual(roadmap_issues.parse_row_number("Row 1: One"), 1)
        self.assertEqual(roadmap_issues.parse_row_number("Row 11: Eleven"), 11)
        self.assertIsNone(roadmap_issues.parse_row_number("Row 11 Eleven"))
        self.assertIsNone(roadmap_issues.parse_row_number("Arrow 3: x"))


class BodyTests(unittest.TestCase):
    lanes = {"GW": [9, 1], "WB": [2], "DESIGN": [3]}

    def test_brief_fields_are_filled_from_the_data(self) -> None:
        row = make_row(
            1,
            needs=[2, 3],
            calls=["LD-C3", "WAKE"],
            risk="high",
            risk_note="high (chats at rest)",
            size="M-L",
        )
        body = roadmap_issues.render_body(row, self.lanes, {2: 40, 3: 41})
        self.assertIn(
            "**Row:** 1, Title 1 ([roadmap.md]"
            "(https://github.com/eugene-plexus/specs/blob/main/docs/design/roadmap.md)",
            body,
        )
        self.assertIn(
            "**Lane:** GW, position 2 of 2 | **Risk:** high (chats at rest) | **Size:** M-L", body
        )
        self.assertIn("**Needs (merged first):** rows 2 (#40), 3 (#41)", body)
        self.assertIn(
            "[doc-a.md](https://github.com/eugene-plexus/specs/blob/main/docs/design/doc-a.md)",
            body,
        )
        self.assertIn("LD-C3, WAKE. Builders build the recommended option until Troy answers", body)
        self.assertIn("(development plan, P4)", body)
        self.assertIn("**Repositories:** `gateway`, `specs`", body)
        self.assertIn("`openapi/gateway.yaml`, `openapi/control.yaml` (possibly)", body)
        self.assertIn("- `gateway/src/a.py`", body)
        self.assertIn("**Do not change:** files that other lanes' in-progress rows own", body)
        self.assertIn(
            "**The test that must fail before the change:** (the orchestrator fills this in", body
        )
        self.assertIn("- The reviewer's findings answered", body)
        self.assertIn("## What it is\n\nIt does a thing people can see\n", body)
        self.assertIn("## Why here, and what it needs\n\nBecause it is first\n", body)

    def test_only_a_high_risk_row_waits_on_the_reviewer(self) -> None:
        low = roadmap_issues.render_body(make_row(1, risk="low"), self.lanes, {})
        self.assertNotIn("reviewer", low)
        self.assertIn("CI green in every repository", low)

    def test_migration_number_is_for_workbench_only(self) -> None:
        wb = roadmap_issues.render_body(make_row(2, lane="WB"), self.lanes, {})
        gw = roadmap_issues.render_body(make_row(1), self.lanes, {})
        self.assertIn(
            "**Store migration number (Workbench only):** "
            "assigned by the orchestrator when the row starts",
            wb,
        )
        self.assertNotIn("Store migration number", gw)

    def test_needs_link_to_a_row_without_an_issue_says_pending(self) -> None:
        row = make_row(1, needs=[5])
        body = roadmap_issues.render_body(row, self.lanes, {})
        self.assertIn("**Needs (merged first):** row 5 (issue pending)", body)
        self.assertIn(
            "**Needs (merged first):** none",
            roadmap_issues.render_body(make_row(1), self.lanes, {}),
        )

    def test_empty_fields_are_stated(self) -> None:
        row = make_row(1, contract="", hot_files=[], design_docs=[], calls=[])
        body = roadmap_issues.render_body(row, self.lanes, {})
        self.assertIn("**Contract:** none", body)
        self.assertIn("not known yet", body)
        self.assertIn("Docs: none yet.", body)
        self.assertIn("**Open calls and the default to build:** none.", body)

    def test_contract_text(self) -> None:
        self.assertEqual(roadmap_issues.contract_text("design only"), "design only")
        self.assertEqual(roadmap_issues.contract_text("?"), "not known yet (the design decides)")
        self.assertEqual(
            roadmap_issues.contract_text("components/client-keys.yaml"),
            "`openapi/components/client-keys.yaml`",
        )

    def test_a_design_row_is_done_when_the_design_is_written(self) -> None:
        row = make_row(3, lane="DESIGN", contract="design only", design_state="full")
        body = roadmap_issues.render_body(row, self.lanes, {})
        self.assertIn("- The design is written in docs/design and names its calls:", body)

    def test_summary_is_cut_after_the_title_it_starts_with(self) -> None:
        self.assertEqual(roadmap_issues.what_it_is(make_row(1)), "It does a thing people can see")
        same = make_row(1, summary="Title 1")
        self.assertEqual(roadmap_issues.what_it_is(same), "Title 1")
        other = make_row(1, summary="Something else entirely")
        self.assertEqual(roadmap_issues.what_it_is(other), "Something else entirely")

    def test_hand_filled_lines_survive_a_rewrite(self) -> None:
        row = make_row(2, lane="WB")
        first = roadmap_issues.render_body(row, self.lanes, {})
        self.assertEqual(roadmap_issues.extract_preserved(first), {})
        edited = (
            first.replace(
                "files that other lanes' in-progress rows own "
                "(the orchestrator fills this in when the row starts)",
                "`wb/store.py` while row 7 builds",
            )
            .replace("assigned by the orchestrator when the row starts", "migration 28")
            .replace(
                "(the orchestrator fills this in when the row starts)",
                "test_x fails.\n\nIt also needs test_y.",
            )
        )
        kept = roadmap_issues.extract_preserved(edited.replace("\n", "\r\n"))
        self.assertEqual(kept["Store migration number (Workbench only)"], "migration 28")
        self.assertEqual(kept["Do not change"], "`wb/store.py` while row 7 builds")
        self.assertEqual(
            kept["The test that must fail before the change"],
            "test_x fails.\n\nIt also needs test_y.",
        )
        again = roadmap_issues.render_body(row, self.lanes, {}, preserved=kept)
        self.assertTrue(roadmap_issues.same_text(again, edited))


class RunTests(unittest.TestCase):
    def doc(self) -> dict[str, Any]:
        rows = [
            make_row(1, lane="GW"),
            make_row(2, lane="GW", needs=[3, 1]),
            make_row(3, lane="WB", design_state="short", needs=[1]),
        ]
        return {"lanes": {"GW": [1, 2], "WB": [3]}, "rows": rows}

    def run_it(
        self, tracker: FakeTracker, doc: dict[str, Any] | None = None, **flags: Any
    ) -> dict[str, Any]:
        return roadmap_issues.run(doc or self.doc(), tracker, out=quiet, **flags)

    def test_creates_every_row_and_links_needs_made_in_the_same_run(self) -> None:
        tracker = FakeTracker()
        result = self.run_it(tracker)
        self.assertEqual(result["numbers"], {1: 21, 2: 22, 3: 23})
        # Row 2 needs rows 3 and 1; row 3 is made after row 2, so pass 2 fixes the link.
        self.assertIn("rows 3 (#23), 1 (#21)", tracker.issues[22]["body"])
        self.assertNotIn("pending", tracker.issues[22]["body"])
        self.assertEqual(
            sorted(tracker.issues[22]["labels"]),
            sorted(["row", "lane:GW", "risk:cross", "size:M", "design:ready", "status:blocked"]),
        )
        self.assertIn("status:needs-design", tracker.issues[23]["labels"])
        self.assertIn("status:ready", tracker.issues[21]["labels"])
        self.assertEqual(set(tracker.live_labels), {n for n, _, _ in roadmap_issues.LABEL_TABLE})

    def test_dry_run_writes_nothing_and_predicts_numbers(self) -> None:
        tracker = FakeTracker()
        lines: list[str] = []
        result = roadmap_issues.run(self.doc(), tracker, dry_run=True, show={2}, out=lines.append)
        self.assertEqual(tracker.writes, 0)
        self.assertEqual(tracker.issues, {})
        self.assertEqual(result["numbers"], {1: 21, 2: 22, 3: 23})
        text = "\n".join(lines)
        self.assertIn("would create #22 Row 2: Title 2", text)
        self.assertIn("rows 3 (#23), 1 (#21)", text)

    def test_second_run_changes_nothing(self) -> None:
        tracker = FakeTracker()
        self.run_it(tracker)
        writes = tracker.writes
        plain = self.run_it(tracker)
        self.assertEqual(plain["tally"]["created"], 0)
        updating = self.run_it(tracker, update=True)
        self.assertEqual(updating["tally"]["created"], 0)
        self.assertEqual(updating["tally"]["updated"], 0)
        self.assertEqual(updating["tally"]["unchanged"], 3)
        self.assertEqual(tracker.writes, writes)

    def test_plain_run_leaves_existing_issues_alone(self) -> None:
        tracker = FakeTracker()
        self.run_it(tracker)
        tracker.issues[21]["body"] = "someone rewrote this"
        changed = self.doc()
        changed["rows"][0]["title"] = "A new title"
        self.run_it(tracker, changed)
        self.assertEqual(tracker.issues[21]["body"], "someone rewrote this")
        self.assertEqual(tracker.issues[21]["title"], "Row 1: Title 1")

    def test_update_rewrites_but_keeps_hand_filled_lines_and_other_labels(self) -> None:
        tracker = FakeTracker()
        self.run_it(tracker)
        issue = tracker.issues[23]
        issue["body"] = issue["body"].replace(
            "files that other lanes' in-progress rows own "
            "(the orchestrator fills this in when the row starts)",
            "`wb/store.py`",
        )
        issue["labels"].append("good first issue")
        doc = self.doc()
        doc["rows"][2]["summary"] = "Title 3. A different summary"
        self.run_it(tracker, doc, update=True)
        self.assertIn("**Do not change:** `wb/store.py`", issue["body"])
        self.assertIn("A different summary", issue["body"])
        self.assertIn("good first issue", issue["labels"])

    def test_update_never_changes_a_building_status(self) -> None:
        tracker = FakeTracker()
        self.run_it(tracker)
        tracker.issues[22]["labels"] = [
            label for label in tracker.issues[22]["labels"] if label != "status:blocked"
        ] + ["status:building"]
        self.run_it(tracker, update=True)
        statuses = [x for x in tracker.issues[22]["labels"] if x.startswith("status:")]
        self.assertEqual(statuses, ["status:building"])

    def test_closing_a_needed_row_unblocks_on_update(self) -> None:
        tracker = FakeTracker()
        self.run_it(tracker)
        tracker.issues[21]["state"] = "CLOSED"
        tracker.issues[23]["state"] = "CLOSED"
        self.run_it(tracker, update=True)
        self.assertIn("status:ready", tracker.issues[22]["labels"])
        self.assertNotIn("status:blocked", tracker.issues[22]["labels"])

    def test_a_closed_issue_is_never_reopened_or_edited(self) -> None:
        tracker = FakeTracker()
        self.run_it(tracker)
        tracker.issues[21]["state"] = "CLOSED"
        tracker.issues[21]["body"] = "the record"
        before = deepcopy(tracker.issues[21])
        doc = self.doc()
        doc["rows"][0]["title"] = "Changed"
        result = self.run_it(tracker, doc, update=True)
        self.assertEqual(tracker.issues[21], before)
        self.assertEqual(result["tally"]["closed"], 1)

    def test_issues_without_the_row_label_are_never_touched(self) -> None:
        stranger = {
            "number": 5,
            "title": "Row 1: not ours",
            "body": "x",
            "state": "OPEN",
            "labels": ["bug"],
        }
        tracker = FakeTracker([stranger])
        self.run_it(tracker, update=True)
        self.assertEqual(tracker.issues[5], stranger)
        self.assertEqual(len(tracker.issues), 4)

    def test_write_back_adds_the_issue_numbers(self) -> None:
        doc = self.doc()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rows.json"
            path.write_text(
                json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
            )
            self.assertTrue(roadmap_issues.write_numbers(path, doc, {1: 21, 2: 22, 3: 23}))
            self.assertEqual(
                [row["issue"] for row in json.loads(path.read_text(encoding="utf-8"))["rows"]],
                [21, 22, 23],
            )
            self.assertFalse(roadmap_issues.write_numbers(path, doc, {1: 21, 2: 22, 3: 23}))

    def test_data_that_names_a_missing_row_is_refused(self) -> None:
        doc = self.doc()
        doc["rows"][0]["needs"] = [99]
        with self.assertRaises(ValueError):
            self.run_it(FakeTracker(), doc)


class DataFileTests(unittest.TestCase):
    def test_roadmap_rows_file_is_readable_by_the_script(self) -> None:
        doc = json.loads(ROWS_FILE.read_text(encoding="utf-8"))
        roadmap_issues.check_data(doc)
        for row in doc["rows"]:
            with self.subTest(row=row["row"]):
                roadmap_issues.render_body(row, doc["lanes"], {})
                self.assertIn(row["row"], doc["lanes"][row["lane"]])


if __name__ == "__main__":
    unittest.main()
