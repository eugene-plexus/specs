"""Row 48 keeps Library pagination opt-in and safe across rescans."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

CONTRACT = Path(__file__).resolve().parents[1] / "openapi" / "library.yaml"


class LibraryPaginationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        cls.operation = cls.contract["paths"]["/v1/models"]["get"]
        cls.parameters = {
            parameter["name"]: parameter for parameter in cls.operation["parameters"]
        }
        cls.model_list = cls.contract["components"]["schemas"]["LibraryModelList"]

    def test_limit_is_optional_and_bounded_without_an_implicit_page_size(self) -> None:
        limit = self.parameters["limit"]
        self.assertEqual(limit["in"], "query")
        self.assertIs(limit["required"], False)
        self.assertEqual(limit["schema"]["type"], "integer")
        self.assertEqual(limit["schema"]["minimum"], 1)
        self.assertEqual(limit["schema"]["maximum"], 500)
        self.assertNotIn("default", limit["schema"])

    def test_cursor_is_an_optional_nonempty_opaque_string(self) -> None:
        cursor = self.parameters["cursor"]
        self.assertEqual(cursor["in"], "query")
        self.assertIs(cursor["required"], False)
        self.assertEqual(cursor["schema"]["type"], "string")
        self.assertEqual(cursor["schema"]["minLength"], 1)
        self.assertNotIn("default", cursor["schema"])
        self.assertIn("Opaque", cursor["description"])
        self.assertIn("nextCursor", cursor["description"])

    def test_unpaged_list_and_scan_timestamp_remain_compatible(self) -> None:
        description = " ".join(self.operation["description"].split())
        self.assertIn("Without `limit` or `cursor`, returns every model", description)
        response = self.operation["responses"]["200"]["content"]["application/json"]
        self.assertEqual(
            response["schema"], {"$ref": "#/components/schemas/LibraryModelList"}
        )
        self.assertEqual(self.model_list["required"], ["models"])
        self.assertEqual(
            self.model_list["properties"]["models"],
            {
                "type": "array",
                "items": {"$ref": "#/components/schemas/LibraryModel"},
            },
        )
        last_scan = self.model_list["properties"]["lastScanAt"]
        self.assertEqual(last_scan["type"], "string")
        self.assertEqual(last_scan["format"], "date-time")

    def test_cursor_tracks_the_sort_key_and_survives_a_removed_boundary(self) -> None:
        description = " ".join(self.operation["description"].split())
        self.assertIn("same stable order as the full list", description)
        self.assertIn("sort key", description)
        self.assertIn("not an offset", description)
        self.assertIn("adds or removes models", description)
        self.assertIn("last model is removed", description)
        self.assertIn("without repeating or skipping", description)

    def test_path_lookup_ignores_even_invalid_paging_parameters(self) -> None:
        path = self.parameters["path"]
        self.assertEqual(path["in"], "query")
        self.assertIs(path["required"], False)
        self.assertEqual(path["schema"], {"type": "string"})
        description = " ".join(path["description"].split())
        self.assertIn("return the single entry", description)
        self.assertIn("case-folded on Windows", description)
        self.assertIn("ignores `limit` and `cursor`, even if invalid", description)

    def test_next_cursor_is_optional_and_absent_when_no_more_pages_remain(self) -> None:
        cursor = self.model_list["properties"]["nextCursor"]
        self.assertEqual(cursor["type"], "string")
        self.assertEqual(cursor["minLength"], 1)
        self.assertNotIn("nextCursor", self.model_list["required"])
        description = " ".join(cursor["description"].split())
        self.assertIn("Opaque", description)
        self.assertIn("more models remain", description)
        self.assertIn("Omitted on the last page", description)
        self.assertIn("unpaginated", description)
        self.assertIn("path", description)

    def test_bad_paging_returns_a_problem_with_a_sentence_naming_the_cause(
        self,
    ) -> None:
        response = self.operation["responses"]["400"]
        content = response["content"]["application/problem+json"]
        self.assertEqual(
            content["schema"],
            {"$ref": "components/common.yaml#/components/schemas/Problem"},
        )
        description = " ".join(response["description"].split())
        for cause in ("limit", "unknown", "malformed"):
            self.assertIn(cause, description)
        self.assertIn("sentence", description)
        for name, cause in (
            ("invalidLimit", "between 1 and 500"),
            ("malformedCursor", "malformed"),
            ("unknownCursor", "not issued by this Library"),
        ):
            with self.subTest(example=name):
                problem = content["examples"][name]["value"]
                self.assertEqual(problem["status"], 400)
                self.assertIn("type", problem)
                self.assertIn("title", problem)
                self.assertIn(cause, problem["detail"])
                self.assertTrue(problem["detail"].endswith("."))


if __name__ == "__main__":
    unittest.main()
