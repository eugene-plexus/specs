"""Row 48b exposes saved Library settings and safe-mode folder answers."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

OPENAPI = Path(__file__).resolve().parents[1] / "openapi"


class LibraryDownContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library = yaml.safe_load(
            (OPENAPI / "library.yaml").read_text(encoding="utf-8")
        )
        cls.gateway = yaml.safe_load(
            (OPENAPI / "gateway.yaml").read_text(encoding="utf-8")
        )
        cls.agent = yaml.safe_load(
            (OPENAPI / "agent.yaml").read_text(encoding="utf-8")
        )["components"]["schemas"]
        cls.gateway_schemas = cls.gateway["components"]["schemas"]

    def test_folder_safe_mode_is_optional_read_only_and_defaults_false(self) -> None:
        operation = self.library["paths"]["/v1/folders"]["get"]
        response = operation["responses"]["200"]["content"]["application/json"]
        self.assertEqual(
            response["schema"], {"$ref": "#/components/schemas/LibraryFolderList"}
        )
        folders = self.library["components"]["schemas"]["LibraryFolderList"]
        safe_mode = folders["properties"]["safeMode"]
        self.assertEqual(safe_mode["type"], "boolean")
        self.assertIs(safe_mode["readOnly"], True)
        self.assertIs(safe_mode["default"], False)
        self.assertNotIn("safeMode", folders["required"])

    def test_safe_mode_folder_answer_preserves_saved_mounts(self) -> None:
        folders = self.library["components"]["schemas"]["LibraryFolderList"]
        description = " ".join(
            folders["properties"]["safeMode"]["description"].split()
        )
        for meaning in ("ignores its saved config", "keep their saved folder list"):
            with self.subTest(meaning=meaning):
                self.assertIn(meaning, description)

    def test_gateway_info_requires_library_status(self) -> None:
        operation = self.gateway["paths"]["/v1/info"]["get"]
        self.assertEqual(operation["operationId"], "getInfo")
        response = operation["responses"]["200"]["content"]["application/json"]
        self.assertEqual(response["schema"], {"$ref": "#/components/schemas/GatewayInfo"})
        info = self.gateway_schemas["GatewayInfo"]
        self.assertIn("library", info["required"])
        self.assertEqual(
            info["properties"]["library"],
            {"$ref": "#/components/schemas/GatewayLibraryStatus"},
        )

    def test_gateway_library_reachability_is_unknown_before_first_check(self) -> None:
        status = self.gateway_schemas["GatewayLibraryStatus"]
        reachable = status["properties"]["reachable"]
        self.assertCountEqual(reachable["type"], ["boolean", "null"])
        self.assertIn("before the first check", reachable["description"])
        self.assertNotIn("default", reachable)

    def test_gateway_library_outage_reports_time_cause_and_saved_model_count(self) -> None:
        status = self.gateway_schemas["GatewayLibraryStatus"]
        self.assertCountEqual(
            status["required"], ["reachable", "since", "cause", "modelsOnSavedSettings"]
        )
        properties = status["properties"]
        self.assertCountEqual(properties["since"]["type"], ["string", "null"])
        self.assertEqual(properties["since"]["format"], "date-time")
        self.assertIn("first observed", properties["since"]["description"])
        self.assertCountEqual(properties["cause"]["type"], ["string", "null"])
        self.assertIn("observed cause", properties["cause"]["description"])
        count = properties["modelsOnSavedSettings"]
        self.assertEqual(count["type"], "integer")
        self.assertEqual(count["minimum"], 0)
        self.assertIn("distinct model paths", count["description"])
        self.assertIn("after a restart", count["description"])

    def test_profile_outage_default_has_no_limit_and_keeps_expert_overrides(self) -> None:
        operation = self.gateway["paths"]["/v1/chat/completions"]["post"]
        description = " ".join(operation["description"].split())
        for meaning in (
            "profileMaxStaleSeconds",
            "null by default",
            "no time limit",
            "Zero disables stale reuse",
            "502/503/504",
            "successful empty result clears old defaults",
            "loaded as stale",
        ):
            with self.subTest(meaning=meaning):
                self.assertIn(meaning, description)
        self.assertNotIn("300 by default", description)

    def test_runtime_reuses_local_path_note_for_unchecked_copy(self) -> None:
        runtime = self.agent["Runtime"]
        note = runtime["properties"]["localPathNote"]
        self.assertEqual(note["type"], "string")
        self.assertIs(note["readOnly"], True)
        self.assertNotIn("localPathNote", runtime["required"])
        self.assertNotIn("localPathNote", self.agent["RuntimeSpec"]["properties"])
        description = " ".join(note["description"].split())
        for meaning in (
            "Started from this machine's copy",
            "folder root",
            "observed cause",
            "5 s",
            "next start",
            "missing file in a readable folder",
        ):
            with self.subTest(meaning=meaning):
                self.assertIn(meaning, description)


if __name__ == "__main__":
    unittest.main()
