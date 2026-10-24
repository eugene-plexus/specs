"""Offline contracts for Strata preparation, profiles and applied launch settings."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

OPENAPI = Path(__file__).resolve().parents[1] / "openapi"


class StrataSettingsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = yaml.safe_load(
            (OPENAPI / "components/common.yaml").read_text(encoding="utf-8")
        )["components"]["schemas"]
        cls.agent = yaml.safe_load(
            (OPENAPI / "agent.yaml").read_text(encoding="utf-8")
        )["components"]["schemas"]
        cls.library = yaml.safe_load(
            (OPENAPI / "library.yaml").read_text(encoding="utf-8")
        )["components"]["schemas"]

    def test_projection_is_an_explicit_off_or_on_choice(self) -> None:
        mode = self.common["SpeedProjectionMode"]
        self.assertEqual(mode["type"], "string")
        self.assertEqual(mode["enum"], ["off", "on"])
        self.assertNotIn("default", mode)

    def test_projection_description_leads_with_changed_answers(self) -> None:
        description = self.common["SpeedProjectionMode"]["description"]
        first_line = description.splitlines()[0].lower()
        self.assertIn("changes", first_line)
        self.assertIn("answers", first_line)
        for words in ("experimental", "refusal", "0.2-0.4%", "speed-up"):
            with self.subTest(words=words):
                self.assertIn(words, description.lower())

    def test_preparation_advertises_projection_choices_per_model(self) -> None:
        preparation = self.common["ModelPreparation"]
        modes = preparation["properties"]["speedProjectionModes"]
        self.assertEqual(modes["type"], "array")
        self.assertTrue(modes["uniqueItems"])
        self.assertEqual(
            modes["items"], {"$ref": "#/components/schemas/SpeedProjectionMode"}
        )
        self.assertNotIn("speedProjectionModes", preparation["required"])
        self.assertNotIn("default", modes)

    def test_preparation_keeps_existing_fields_and_defaults_projection_off(
        self,
    ) -> None:
        intent = self.common["PreparationIntent"]
        self.assertEqual(intent["required"], ["engine"])
        self.assertFalse(intent["additionalProperties"])
        properties = intent["properties"]
        self.assertEqual(
            properties["engine"], {"$ref": "#/components/schemas/EngineKind"}
        )
        self.assertEqual(properties["contextSize"]["type"], ["integer", "null"])
        self.assertEqual(properties["contextSize"]["minimum"], 1)
        self.assertEqual(properties["vision"]["default"], "off")
        self.assertEqual(properties["speedProjection"]["default"], "off")
        self.assertEqual(
            properties["speedProjection"]["$ref"],
            "#/components/schemas/SpeedProjectionMode",
        )

    def test_preparation_intent_is_available_to_library_codegen(self) -> None:
        self.assertEqual(
            self.library["PreparationIntent"],
            {"$ref": "components/common.yaml#/components/schemas/PreparationIntent"},
        )

    def test_ci_runs_the_strata_contract_checks(self) -> None:
        workflow = yaml.safe_load(
            (OPENAPI.parent / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        )
        steps = workflow["jobs"]["validate-openapi"]["steps"]
        self.assertTrue(
            any(
                "python scripts/test_strata_settings_contract.py" in step.get("run", "")
                for step in steps
            )
        )

    def test_gpu_selection_is_ordered_nonempty_and_has_no_duplicates(self) -> None:
        cards = self.common["StrataGpuSelection"]
        self.assertEqual(cards["type"], "array")
        self.assertEqual(cards["minItems"], 1)
        self.assertTrue(cards["uniqueItems"])
        self.assertEqual(cards["items"], {"type": "integer", "minimum": 0})
        self.assertIn("main", cards["description"])
        self.assertIn("node", cards["description"])
        self.assertNotIn("default", cards)

    def test_preparation_uses_the_shared_gpu_and_layer_split_shapes(self) -> None:
        properties = self.common["PreparationIntent"]["properties"]
        self.assertEqual(
            properties["gpus"]["$ref"], "#/components/schemas/StrataGpuSelection"
        )
        self.assertNotIn("default", properties["gpus"])
        self.assertEqual(
            properties["layerSplit"]["$ref"], "#/components/schemas/StrataLayerSplit"
        )
        self.assertEqual(properties["layerSplit"]["default"], "auto")

    def test_layer_split_describes_boundaries_instead_of_counts(self) -> None:
        split = self.common["StrataLayerSplit"]
        self.assertEqual(split["type"], "string")
        self.assertEqual(split["minLength"], 1)
        description = " ".join(split["description"].split())
        for words in ("auto", "first layer", "16,32", "rising", "not a count"):
            with self.subTest(words=words):
                self.assertIn(words, description)
        self.assertNotIn("default", split)

    def test_profiles_and_runtime_intents_keep_engine_owned_flags(self) -> None:
        for schema in (
            self.library["ModelProfileSpec"],
            self.library["ModelProfile"],
            self.agent["RuntimeSpec"],
        ):
            flags = schema["properties"]["flags"]
            self.assertEqual(flags["type"], "object")
            self.assertTrue(flags["additionalProperties"])
        description = self.library["ModelProfileSpec"]["properties"]["flags"][
            "description"
        ]
        for field in ("speedProjection", "gpus", "layerSplit"):
            with self.subTest(field=field):
                self.assertIn(field, description)

    def test_runtime_reports_effective_launch_without_an_intent_default(self) -> None:
        runtime = self.agent["Runtime"]
        field = runtime["properties"]["effectiveLaunch"]
        self.assertEqual(field["$ref"], "#/components/schemas/StrataEffectiveLaunch")
        self.assertTrue(field["readOnly"])
        self.assertNotIn("default", field)
        self.assertNotIn("effectiveLaunch", runtime["required"])
        self.assertNotIn("effectiveLaunch", self.agent["RuntimeSpec"]["properties"])

    def test_effective_settings_require_applied_values_and_have_no_defaults(
        self,
    ) -> None:
        effective = self.agent["StrataEffectiveLaunch"]
        self.assertTrue(effective["readOnly"])
        self.assertFalse(effective["additionalProperties"])
        self.assertCountEqual(
            effective["required"], ["speedProjection", "gpus", "layerSplit"]
        )
        properties = effective["properties"]
        for field in ("speedProjection", "gpus", "layerSplit"):
            with self.subTest(field=field):
                self.assertNotIn("default", properties[field])
        self.assertEqual(
            properties["speedProjection"]["$ref"],
            "components/common.yaml#/components/schemas/SpeedProjectionMode",
        )
        self.assertEqual(
            properties["gpus"]["$ref"],
            "components/common.yaml#/components/schemas/StrataGpuSelection",
        )
        self.assertCountEqual(
            properties["layerSplit"]["anyOf"],
            [
                {"$ref": "components/common.yaml#/components/schemas/StrataLayerSplit"},
                {"type": "null"},
            ],
        )
        description = " ".join(effective["description"].split()).lower()
        self.assertIn("launch configuration", description)
        self.assertIn("not", description)
        self.assertIn("unknown", description)


if __name__ == "__main__":
    unittest.main()
