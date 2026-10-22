"""Author sampling defaults survive profile and model contract round trips."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

CONTRACT = Path(__file__).resolve().parents[1] / "openapi" / "library.yaml"


class AuthorSamplingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schemas = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))[
            "components"
        ]["schemas"]

    def test_profile_author_sampling_is_optional_and_on_by_default(self) -> None:
        for name in ("ModelProfileSpec", "ModelProfile"):
            with self.subTest(schema=name):
                schema = self.schemas[name]
                field = schema["properties"]["authorSampling"]
                self.assertEqual(field["type"], "boolean")
                self.assertIs(field["default"], True)
                self.assertNotIn("authorSampling", schema["required"])

    def test_profile_top_k_is_optional_and_nonnegative(self) -> None:
        for name in ("ModelProfileSpec", "ModelProfile"):
            with self.subTest(schema=name):
                schema = self.schemas[name]
                field = schema["properties"]["topK"]
                self.assertEqual(field["type"], "integer")
                self.assertEqual(field["minimum"], 0)
                self.assertNotIn("default", field)
                self.assertNotIn("topK", schema["required"])

    def test_profile_min_p_is_optional_and_bounded(self) -> None:
        for name in ("ModelProfileSpec", "ModelProfile"):
            with self.subTest(schema=name):
                schema = self.schemas[name]
                field = schema["properties"]["minP"]
                self.assertEqual(field["type"], "number")
                self.assertEqual(field["minimum"], 0)
                self.assertEqual(field["maximum"], 1)
                self.assertNotIn("default", field)
                self.assertNotIn("minP", schema["required"])

    def test_recommended_sampling_has_optional_min_p(self) -> None:
        schema = self.schemas["RecommendedSampling"]
        field = schema["properties"]["minP"]
        self.assertEqual(field["type"], "number")
        self.assertEqual(field["minimum"], 0)
        self.assertEqual(field["maximum"], 1)
        self.assertNotIn("default", field)
        self.assertNotIn("minP", schema.get("required", []))

    def test_recommended_sampling_has_optional_source(self) -> None:
        schema = self.schemas["RecommendedSampling"]
        self.assertEqual(
            schema["properties"]["source"]["$ref"],
            "#/components/schemas/RecommendedSamplingSource",
        )
        source = self.schemas["RecommendedSamplingSource"]
        self.assertEqual(source["type"], "string")
        self.assertCountEqual(source["enum"], ["gguf", "generation_config"])
        self.assertNotIn("source", schema.get("required", []))

    def test_safetensors_reports_optional_author_sampling(self) -> None:
        schema = self.schemas["SafetensorsDetail"]
        self.assertEqual(
            schema["properties"]["recommendedSampling"]["$ref"],
            "#/components/schemas/RecommendedSampling",
        )
        self.assertNotIn("recommendedSampling", schema.get("required", []))

    def test_author_sampling_is_documented_as_gateway_defaults(self) -> None:
        description = self.schemas["RecommendedSampling"]["description"]
        self.assertIn("applied by the gateway as defaults", description)
        self.assertNotIn("never applied", description)


if __name__ == "__main__":
    unittest.main()
