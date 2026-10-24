"""Row 43 reports observed card health and temporary launches on fewer cards."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

OPENAPI = Path(__file__).resolve().parents[1] / "openapi"
HEALTH_FIELDS = {
    "uuid",
    "pciBusId",
    "pcieLink",
    "powerLimitWatts",
    "powerDefaultLimitWatts",
    "throttleReasons",
    "uncorrectedMemoryErrors",
    "peers",
}


class CardsLeftContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = yaml.safe_load(
            (OPENAPI / "components/common.yaml").read_text(encoding="utf-8")
        )["components"]["schemas"]
        cls.agent = yaml.safe_load(
            (OPENAPI / "agent.yaml").read_text(encoding="utf-8")
        )["components"]["schemas"]

    def test_device_health_fields_are_optional_nullable_and_have_no_defaults(
        self,
    ) -> None:
        device = self.common["ComputeDevice"]
        for name in sorted(HEALTH_FIELDS):
            with self.subTest(field=name):
                field = device["properties"][name]
                self.assertNotIn(name, device["required"])
                self.assertNotIn("default", field)
                if "anyOf" in field:
                    self.assertIn({"type": "null"}, field["anyOf"])
                else:
                    self.assertIn("null", field["type"])

    def test_device_identity_accepts_vendor_ids_without_an_rfc_uuid_format(
        self,
    ) -> None:
        device = self.common["ComputeDevice"]["properties"]
        for name in ("uuid", "pciBusId"):
            with self.subTest(field=name):
                self.assertCountEqual(device[name]["type"], ["string", "null"])
                self.assertEqual(device[name]["minLength"], 1)
                self.assertNotIn("format", device[name])

    def test_pcie_link_preserves_individually_unreadable_measurements(self) -> None:
        field = self.common["ComputeDevice"]["properties"]["pcieLink"]
        self.assertCountEqual(
            field["anyOf"],
            [
                {"$ref": "#/components/schemas/ComputeDevicePcieLink"},
                {"type": "null"},
            ],
        )
        link = self.common["ComputeDevicePcieLink"]
        measurements = {"generation", "width", "maxGeneration", "maxWidth"}
        self.assertEqual(link["type"], "object")
        self.assertEqual(set(link["required"]), measurements)
        self.assertEqual(set(link["properties"]), measurements)
        for name in sorted(measurements):
            with self.subTest(field=name):
                measurement = link["properties"][name]
                self.assertCountEqual(measurement["type"], ["integer", "null"])
                self.assertEqual(measurement["minimum"], 1)
                self.assertNotIn("default", measurement)

    def test_power_and_ecc_readings_are_nonnegative_and_distinguish_unknown(
        self,
    ) -> None:
        device = self.common["ComputeDevice"]["properties"]
        for name, kind in (
            ("powerLimitWatts", "number"),
            ("powerDefaultLimitWatts", "number"),
            ("uncorrectedMemoryErrors", "integer"),
        ):
            with self.subTest(field=name):
                self.assertCountEqual(device[name]["type"], [kind, "null"])
                self.assertEqual(device[name]["minimum"], 0)
        self.assertEqual(device["uncorrectedMemoryErrors"]["format"], "int64")

    def test_throttle_reasons_use_a_closed_vocabulary(self) -> None:
        field = self.common["ComputeDevice"]["properties"]["throttleReasons"]
        self.assertCountEqual(field["type"], ["array", "null"])
        self.assertIs(field["uniqueItems"], True)
        self.assertEqual(
            field["items"],
            {"$ref": "#/components/schemas/ComputeDeviceThrottleReason"},
        )
        reason = self.common["ComputeDeviceThrottleReason"]
        self.assertEqual(reason["type"], "string")
        self.assertCountEqual(
            reason["enum"], ["thermal", "power-cap", "hardware-slowdown", "other"]
        )

    def test_peers_are_device_ids_and_an_empty_list_is_a_known_result(self) -> None:
        field = self.common["ComputeDevice"]["properties"]["peers"]
        self.assertCountEqual(field["type"], ["array", "null"])
        self.assertIs(field["uniqueItems"], True)
        self.assertEqual(field["items"], {"type": "string", "minLength": 1})
        self.assertNotIn("minItems", field)
        self.assertNotIn("default", field)

    def test_runtime_records_uuids_from_the_last_successful_start(self) -> None:
        runtime = self.agent["Runtime"]
        field = runtime["properties"]["lastDevices"]
        self.assertEqual(field["type"], "array")
        self.assertEqual(field["items"], {"type": "string", "minLength": 1})
        self.assertIs(field["uniqueItems"], True)
        self.assertIs(field["readOnly"], True)
        self.assertNotIn("lastDevices", runtime["required"])
        self.assertNotIn("default", field)

    def test_fewer_cards_reports_missing_identity_and_launch_changes(self) -> None:
        runtime = self.agent["Runtime"]
        field = runtime["properties"]["startedOnFewerCards"]
        self.assertIs(field["readOnly"], True)
        self.assertNotIn("startedOnFewerCards", runtime["required"])
        self.assertNotIn("default", field)
        self.assertCountEqual(
            field["anyOf"],
            [
                {"$ref": "#/components/schemas/RuntimeStartedOnFewerCards"},
                {"type": "null"},
            ],
        )
        observation = self.agent["RuntimeStartedOnFewerCards"]
        self.assertEqual(observation["type"], "object")
        self.assertIs(observation["readOnly"], True)
        self.assertEqual(set(observation["required"]), {"missing", "changes"})
        missing = observation["properties"]["missing"]
        self.assertEqual(missing["type"], "array")
        self.assertEqual(missing["minItems"], 1)
        self.assertEqual(
            missing["items"], {"$ref": "#/components/schemas/RuntimeMissingDevice"}
        )
        changes = observation["properties"]["changes"]
        self.assertEqual(changes["type"], "array")
        self.assertEqual(changes["items"], {"type": "string", "minLength": 1})
        device = self.agent["RuntimeMissingDevice"]
        self.assertEqual(device["type"], "object")
        self.assertEqual(set(device["required"]), {"uuid", "name", "lastIndex"})
        self.assertEqual(device["properties"]["uuid"]["type"], "string")
        self.assertEqual(device["properties"]["name"]["type"], "string")
        self.assertEqual(device["properties"]["lastIndex"]["type"], "integer")
        self.assertEqual(device["properties"]["lastIndex"]["minimum"], 0)

    def test_runtime_observations_are_excluded_from_declarations(self) -> None:
        for name in ("lastDevices", "startedOnFewerCards"):
            with self.subTest(field=name):
                self.assertIn(name, self.agent["Runtime"]["properties"])
                self.assertNotIn(name, self.agent["RuntimeSpec"]["properties"])

    def test_missing_card_policy_uses_engine_flags_with_an_explicit_override(
        self,
    ) -> None:
        flags = self.agent["RuntimeSpec"]["properties"]["flags"]
        self.assertIs(flags["additionalProperties"], True)
        description = " ".join(flags["description"].split())
        self.assertIn("missingCard", description)
        self.assertIn("start-on-cards-left", description)
        self.assertIn("default", description)
        self.assertIn("do-not-start", description)
        self.assertIn("profile is not changed", description)


if __name__ == "__main__":
    unittest.main()
