"""The CPU proof contract can carry a complete, labelled measurement.

Run with unittest or pytest using a Python with PyYAML installed.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

CONTRACT = Path(__file__).resolve().parents[1] / "openapi" / "library.yaml"


class CpuProofContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schemas = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))["components"]["schemas"]

    def test_cpu_proof_requires_speed_and_measurement_context(self) -> None:
        proof = self.schemas["CpuProof"]
        expected = {
            "decodeTokensPerSecond": "number",
            "promptTokensPerSecond": "number",
            "promptTokens": "integer",
            "decodeTokens": "integer",
            "threads": "integer",
            "machine": "string",
            "engine": "string",
            "measuredOn": "string",
        }
        self.assertEqual(set(proof["required"]), set(expected))
        for name, field_type in expected.items():
            with self.subTest(field=name):
                self.assertEqual(proof["properties"][name]["type"], field_type)
        self.assertEqual(proof["properties"]["measuredOn"]["format"], "date")

    def test_starter_cpu_proof_is_optional_and_nullable(self) -> None:
        model = self.schemas["StarterModel"]
        self.assertNotIn("cpuProof", model["required"])
        self.assertCountEqual(
            model["properties"]["cpuProof"]["anyOf"],
            [{"$ref": "#/components/schemas/CpuProof"}, {"type": "null"}],
        )
        self.assertEqual(
            set(self.schemas["StarterRecommendation"]["properties"]),
            {"sizeClass", "reason"},
        )

    def test_cpu_reason_labels_test_machine_speed_and_configurable_floor(self) -> None:
        reason = self.schemas["StarterRecommendation"]["properties"]["reason"]["description"]
        self.assertIn("cpuProof.decodeTokensPerSecond", reason)
        self.assertIn("starterCpuFloorTokensPerSecond", reason)
        self.assertIn("default 4 tok/s", reason)
        self.assertIn("reason names that machine", reason)
        self.assertIn("No speed is predicted for this machine.", reason)


if __name__ == "__main__":
    unittest.main()
