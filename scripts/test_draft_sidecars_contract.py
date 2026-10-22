"""Draft sidecars share a kind across scanned models and catalogue files."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

OPENAPI = Path(__file__).resolve().parents[1] / "openapi"
DRAFT_KIND_REF = "#/components/schemas/DraftKind"


class DraftSidecarsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schemas = yaml.safe_load(
            (OPENAPI / "library.yaml").read_text(encoding="utf-8")
        )["components"]["schemas"]
        cls.agent_schemas = yaml.safe_load(
            (OPENAPI / "agent.yaml").read_text(encoding="utf-8")
        )["components"]["schemas"]

    def test_draft_kind_keeps_existing_kinds_and_adds_bound_sidecars(self) -> None:
        kind = self.schemas["DraftKind"]
        self.assertEqual(kind["type"], "string")
        self.assertCountEqual(
            kind["enum"], ["mtp", "simple", "dflash", "dspark", "eagle3"]
        )

    def test_bound_sidecars_document_header_binding_and_launch_types(self) -> None:
        description = self.schemas["DraftKind"]["description"]
        for field in (
            "general.architecture",
            "<arch>.target_layers",
            "<arch>.target_hidden_size",
        ):
            with self.subTest(field=field):
                self.assertIn(field, description)
        for kind in ("dflash", "dspark", "eagle3"):
            with self.subTest(kind=kind):
                self.assertIn(f"draft-{kind}", description)

    def test_catalogue_draft_kind_is_optional_nullable_and_shared(self) -> None:
        schema = self.schemas["CatalogueFile"]
        field = schema["properties"]["draftKind"]
        self.assertNotIn("draftKind", schema["required"])
        self.assertCountEqual(
            field["oneOf"], [{"$ref": DRAFT_KIND_REF}, {"type": "null"}]
        )
        self.assertNotIn("default", field)

    def test_catalogue_kind_is_a_name_hint_until_the_header_is_read(self) -> None:
        description = " ".join(
            self.schemas["CatalogueFile"]["properties"]["draftKind"][
                "description"
            ].split()
        )
        self.assertIn("CatalogueModel.draftFiles", description)
        for prefix in ("mtp-", "draft-", "dflash-", "dspark-", "eagle3-"):
            with self.subTest(prefix=prefix):
                self.assertIn(prefix, description)
        self.assertIn("after the download", description)
        self.assertIn("the header decides", description)

    def test_scanned_draft_files_use_the_same_kind(self) -> None:
        schema = self.schemas["DraftFile"]
        self.assertIn("kind", schema["required"])
        self.assertEqual(schema["properties"]["kind"], {"$ref": DRAFT_KIND_REF})

    def test_draft_with_names_header_selected_types(self) -> None:
        description = " ".join(self.agent_schemas["DraftWith"]["description"].split())
        self.assertIn("by the file's own header", description)
        for kind in ("mtp", "simple", "dflash", "dspark", "eagle3"):
            with self.subTest(kind=kind):
                self.assertIn(f"draft-{kind}", description)


if __name__ == "__main__":
    unittest.main()
