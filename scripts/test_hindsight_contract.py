"""Offline MV5b contract checks; no Hindsight install or process is needed."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

CONTRACT = Path(__file__).resolve().parents[1] / "openapi" / "agent.yaml"
REF = "#/components/schemas/"
PROBLEM = "components/common.yaml#/components/responses/Problem"


def prose(value: dict) -> str:
    return " ".join(value["description"].split())


class HindsightContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        cls.schemas = cls.contract["components"]["schemas"]
        cls.paths = cls.contract["paths"]

    def validator(self, name: str) -> Draft202012Validator:
        return Draft202012Validator({"$ref": REF + name, "components": {"schemas": self.schemas}})

    def test_dependency_vocabulary_adds_only_the_memory_server_link(self) -> None:
        surface = self.schemas["AppHubSurface"]
        self.assertEqual(surface["enum"], ["inference", "memory-server"])
        self.assertIn("not a hub client-key scope", prose(surface))
        manifest = self.schemas["AppManifest"]["properties"]
        self.assertEqual(manifest["uses"]["items"], {"$ref": REF + "AppHubSurface"})
        self.assertEqual(manifest["uses"]["default"], ["inference"])

    def test_provider_and_safe_path_are_paired_without_an_implicit_provider(self) -> None:
        manifest = self.schemas["AppManifest"]
        provider = manifest["properties"]["provides"]
        self.assertEqual(provider["enum"], ["memory-server"])
        self.assertNotIn("default", provider)
        self.assertNotIn("provides", manifest["required"])
        valid = {
            "id": "hindsight",
            "name": "Hindsight",
            "source": "pypi",
            "version": "1.0.0",
            "package": "hindsight-api-slim[embedded-db]",
            "entry": "hindsight_api.main:main",
            "provides": "memory-server",
            "providesPath": "/mcp/",
        }
        validator = self.validator("AppManifest")
        validator.validate(valid)
        validator.validate({k: v for k, v in valid.items() if not k.startswith("provides")})
        for invalid in (
            {**valid, "provides": "arbitrary-service"},
            {k: v for k, v in valid.items() if k != "provides"},
            {k: v for k, v in valid.items() if k != "providesPath"},
            *(
                {**valid, "providesPath": path}
                for path in (
                    "https://other/mcp/",
                    "//other/",
                    "/../",
                    "/mcp/?token=secret",
                    "/mcp/#bank",
                )
            ),
        ):
            with self.subTest(manifest=invalid):
                self.assertFalse(validator.is_valid(invalid))

    def test_experimental_badge_is_optional_and_false_for_existing_apps(self) -> None:
        for name in ("AppManifest", "App"):
            with self.subTest(schema=name):
                schema = self.schemas[name]
                field = schema["properties"]["experimental"]
                self.assertEqual(field["type"], "boolean")
                self.assertIs(field["default"], False)
                self.assertNotIn("experimental", schema["required"])

    def test_custom_entries_cannot_supply_or_consume_the_catalogue_link(self) -> None:
        custom = self.paths["/v1/app-catalogue/custom"]["post"]
        description = prose(custom)
        for text in ("provides", "providesPath", "memory-server", "linkSecret", "422"):
            self.assertIn(text, description)
        self.assertIn("even when `allowCustomApps` is on", description)
        self.assertEqual(custom["responses"]["422"], {"$ref": PROBLEM})

    def test_link_delivery_is_local_private_and_rotates_after_purge(self) -> None:
        provider = prose(self.schemas["AppManifest"]["properties"]["provides"])
        for text in (
            "same machine",
            "shipped catalogue",
            "loopback",
            "EUGENE_PLEXUS_APP_MEMORY_SERVER_URL",
            "EUGENE_PLEXUS_APP_MEMORY_SERVER_TOKEN_FILE",
            "owner-only file",
            "systemd credential",
            "third app",
            "re-reads",
            "new secret",
            "uninstall",
            "purge",
        ):
            self.assertIn(text, provider)
        self.assertIn("REST", provider)
        self.assertIn("MCP", provider)

    def test_link_supplies_effective_model_metadata_for_locality_checks(self) -> None:
        provider = prose(self.schemas["AppManifest"]["properties"]["provides"])
        for text in (
            "EUGENE_PLEXUS_APP_MEMORY_SERVER_MODEL_FILE",
            "AppSettings",
            "each call",
            "effective",
            "missing or unreadable",
            "outside",
        ):
            self.assertIn(text, provider)

    def test_install_enforces_entry_availability_without_choosing_a_model(self) -> None:
        install = prose(self.paths["/v1/apps/{id}/install"]["post"])
        for text in ("entry's `installable`", "422", "memoryModel: null", "does not start"):
            self.assertIn(text, install)

    def test_pg0_cleanup_is_idempotent_for_an_absent_instance(self) -> None:
        for action in ("start", "stop"):
            with self.subTest(action=action):
                description = prose(self.paths[f"/v1/apps/{{id}}/{action}"]["post"])
                self.assertIn("absent", description)
                self.assertIn("successful cleanup", description)

    def test_new_placeholders_name_their_source_and_missing_value_behavior(self) -> None:
        environment = prose(self.schemas["AppManifest"]["properties"]["environment"])
        for text in ("{auxPort}", "{memoryModel}", "{linkSecret}", "apps.yaml", "settings"):
            self.assertIn(text, environment)
        self.assertIn("distinct", environment)
        self.assertIn("8190-8289", environment)
        self.assertIn("refused", environment)
        self.assertIn("unset", environment)

    def test_model_selection_is_explicit_nullable_and_closed(self) -> None:
        field = self.schemas["AppMemoryModel"]
        self.assertCountEqual(field["type"], ["string", "null"])
        self.assertEqual(field["minLength"], 1)
        self.assertIsNone(field["default"])
        settings = self.schemas["AppSettings"]
        update = self.schemas["AppSettingsUpdate"]
        self.assertEqual(settings["required"], ["memoryModel"])
        self.assertNotIn("memoryModel", update.get("required", []))
        for name in ("AppSettings", "AppSettingsUpdate"):
            with self.subTest(schema=name):
                schema = self.schemas[name]
                self.assertIs(schema["additionalProperties"], False)
                self.assertEqual(
                    schema["properties"]["memoryModel"], {"$ref": REF + "AppMemoryModel"}
                )
                validator = self.validator(name)
                validator.validate({"memoryModel": None})
                validator.validate({"memoryModel": "owner-chosen-model"})
                self.assertFalse(validator.is_valid({"memoryModel": ""}))
                self.assertFalse(validator.is_valid({"memoryModel": 27}))
                self.assertFalse(validator.is_valid({"linkSecret": "never-in-the-api"}))
        self.assertFalse(self.validator("AppSettings").is_valid({}))
        self.validator("AppSettingsUpdate").validate({})

    def test_model_checks_offer_advice_and_allow_an_expert_model_id(self) -> None:
        description = prose(self.schemas["AppMemoryModel"])
        for text in ("unset", "owner chooses", "never block", "untested", "expert", "locality"):
            self.assertIn(text, description)
        self.assertIn("GET /v1/models", description)

    def test_settings_have_agent_owned_operator_get_and_patch_endpoints(self) -> None:
        path = self.paths["/v1/apps/{id}/settings"]
        self.assertEqual(path["parameters"], [{"$ref": "#/components/parameters/AppId"}])
        for method, operation_id in (("get", "getAppSettings"), ("patch", "updateAppSettings")):
            with self.subTest(method=method):
                operation = path[method]
                self.assertEqual(operation["operationId"], operation_id)
                self.assertIn("operator", prose(operation))
                self.assertIn("configTrio", prose(operation))
                response = operation["responses"]["200"]["content"]["application/json"]
                self.assertEqual(response["schema"], {"$ref": REF + "AppSettings"})
                for status in ("401", "403", "404", "409", "503"):
                    self.assertEqual(operation["responses"][status], {"$ref": PROBLEM})
        request = path["patch"]["requestBody"]
        self.assertIs(request["required"], True)
        self.assertEqual(
            request["content"]["application/json"]["schema"], {"$ref": REF + "AppSettingsUpdate"}
        )
        self.assertEqual(path["patch"]["responses"]["422"], {"$ref": PROBLEM})

    def test_patch_reports_effective_settings_and_names_restart_failure(self) -> None:
        patch = prose(self.paths["/v1/apps/{id}/settings"]["patch"])
        for text in (
            "old process",
            "confirmed stopped",
            "effective",
            "503",
            "observed cause",
            "lastError",
            "stopped app stays stopped",
            "null",
        ):
            self.assertIn(text, patch)
        get = self.paths["/v1/apps/{id}/settings"]["get"]
        self.assertEqual(
            get["responses"]["200"]["content"]["application/json"]["example"],
            {"memoryModel": None},
        )

    def test_app_view_exposes_safe_metadata_without_link_credentials(self) -> None:
        app = self.schemas["App"]
        properties = app["properties"]
        self.assertEqual(properties["settings"], {"$ref": REF + "AppSettings"})
        self.assertEqual(properties["provides"]["enum"], ["memory-server"])
        self.assertEqual(properties["auxPort"]["type"], "integer")
        self.assertEqual(properties["auxPort"]["minimum"], 8190)
        self.assertEqual(properties["auxPort"]["maximum"], 8289)
        for field in ("settings", "provides", "providesPath", "auxPort"):
            self.assertNotIn(field, app["required"])
        for field in properties:
            self.assertNotIn("linksecret", field.lower())
            self.assertNotIn("token", field.lower())

    def test_catalogue_reports_entry_specific_installability_and_cause(self) -> None:
        entry = self.schemas["AppCatalogueEntry"]
        fields = entry["properties"]
        self.assertEqual(fields["installable"]["type"], "boolean")
        self.assertNotIn("default", fields["installable"])
        self.assertNotIn("installable", entry["required"])
        self.assertEqual(fields["reason"]["type"], "string")
        self.assertIn("observed cause", prose(fields["reason"]))
        self.assertIn("Windows", prose(fields["installable"]))
        self.assertIn("agent-account", prose(fields["installable"]))
        self.assertIn("Linux", prose(fields["installable"]))

    def test_hindsight_catalogue_conditions_are_binding(self) -> None:
        description = prose(self.schemas["AppManifest"])
        for text in (
            "hindsight-api-slim[embedded-db]",
            "1.0.0",
            "ApiKeyTenantExtension",
            "HINDSIGHT_API_TENANT_API_KEY",
            "{appSecret}",
            "HINDSIGHT_API_MCP_AUTH_TOKEN",
            "{linkSecret}",
            "pg0://hindsight:{auxPort}",
            "HOME",
            "app's data folder",
            "OTEL",
            "gateway",
            "Experimental",
        ):
            self.assertIn(text, description)

    def test_stop_and_purge_cover_orphan_postgres_and_external_pg0_data(self) -> None:
        for suffix in ("stop", "restart"):
            with self.subTest(action=suffix):
                description = prose(self.paths[f"/v1/apps/{{id}}/{suffix}"]["post"])
                self.assertIn("pg0 stop", description)
                self.assertIn("observed cause", description)
        uninstall = prose(self.paths["/v1/apps/{id}"]["delete"])
        for text in ("pg0 stop", "pg0 drop", "purge", "instance", "observed cause", "link"):
            self.assertIn(text, uninstall)
        start = prose(self.paths["/v1/apps/{id}/start"]["post"])
        self.assertIn("memoryModel", start)
        self.assertIn("Choose the model Hindsight reads your chats with", start)
        self.assertIn("pg0 stop", start)


if __name__ == "__main__":
    unittest.main()
