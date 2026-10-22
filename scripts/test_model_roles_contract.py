"""Model roles share one closed vocabulary and expose effective slot assignments."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

OPENAPI = Path(__file__).resolve().parents[1] / "openapi"
ROLE_REF = "components/common.yaml#/components/schemas/ModelRole"
DEFAULTS = {
    "chat": ("Chat", "chat"),
    "agentic": ("Agentic (tools and code)", "toolCalling"),
    "vision": ("Sees images", "imageInput"),
    "reads-pages": ("Reads pages (OCR)", "imageInput"),
    "image": ("Makes images", "image"),
    "speech-to-text": ("Hears speech", "transcription"),
    "text-to-speech": ("Speaks", "speech"),
    "music": ("Makes music", "audioOutput"),
    "embeddings": ("Embeddings", "embeddings"),
    "rerank": ("Reranks", "rerank"),
    "decision": ("Decisions (yes/no)", "decision"),
}


class ModelRolesContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = yaml.safe_load(
            (OPENAPI / "components/common.yaml").read_text(encoding="utf-8")
        )
        cls.gateway = yaml.safe_load(
            (OPENAPI / "gateway.yaml").read_text(encoding="utf-8")
        )
        cls.schemas = cls.gateway["components"]["schemas"]

    def test_model_role_is_a_shared_closed_enum(self) -> None:
        role = self.common["components"]["schemas"]["ModelRole"]
        self.assertEqual(role["type"], "string")
        self.assertEqual(role["enum"], list(DEFAULTS))
        for schema_name in ("ModelRoleDefinition", "ModelRoleInfo"):
            with self.subTest(schema=schema_name):
                self.assertEqual(
                    self.schemas[schema_name]["properties"]["role"], {"$ref": ROLE_REF}
                )

    def test_roles_endpoint_lists_all_defaults_with_labels_and_capabilities(
        self,
    ) -> None:
        operation = self.gateway["paths"]["/v1/roles"]["get"]
        self.assertEqual(operation["operationId"], "listRoles")
        response = operation["responses"]["200"]["content"]["application/json"]
        self.assertEqual(
            response["schema"], {"$ref": "#/components/schemas/ModelRoleList"}
        )
        roles = self.schemas["ModelRoleList"]
        self.assertIn("roles", roles["required"])
        self.assertEqual(roles["properties"]["roles"]["type"], "array")
        self.assertEqual(
            roles["properties"]["roles"]["items"],
            {"$ref": "#/components/schemas/ModelRoleDefinition"},
        )
        definition = self.schemas["ModelRoleDefinition"]
        self.assertEqual(
            set(definition["required"]),
            {"role", "label", "requiredCapability", "models"},
        )
        self.assertEqual(
            definition["properties"]["requiredCapability"],
            {"$ref": "#/components/schemas/ModelRoleCapability"},
        )
        examples = response["example"]["roles"]
        self.assertEqual([role["role"] for role in examples], list(DEFAULTS))
        for role in examples:
            with self.subTest(role=role["role"]):
                self.assertEqual(
                    (role["label"], role["requiredCapability"]), DEFAULTS[role["role"]]
                )
                self.assertIn(
                    role["requiredCapability"],
                    self.schemas["ModelRoleCapability"]["enum"],
                )
                self.assertIsInstance(role["models"], list)
        self.assertEqual(
            examples[0]["models"], [], "Unassigned roles remain discoverable"
        )

    def test_role_models_preserve_order_and_report_three_capability_states(
        self,
    ) -> None:
        models = self.schemas["ModelRoleDefinition"]["properties"]["models"]
        self.assertEqual(models["type"], "array")
        self.assertNotIn("minItems", models)
        self.assertEqual(
            models["items"], {"$ref": "#/components/schemas/ModelRoleModel"}
        )
        model = self.schemas["ModelRoleModel"]
        self.assertEqual(set(model["required"]), {"model", "capability", "reason"})
        self.assertEqual(model["properties"]["model"]["type"], "string")
        self.assertEqual(
            model["properties"]["capability"],
            {"$ref": "#/components/schemas/ModelRoleCapabilityStatus"},
        )
        self.assertEqual(
            self.schemas["ModelRoleCapabilityStatus"]["enum"], ["yes", "no", "unknown"]
        )
        self.assertIn("configured order", " ".join(models["description"].split()))
        response = self.gateway["paths"]["/v1/roles"]["get"]["responses"]["200"]
        roles = response["content"]["application/json"]["example"]["roles"]
        assigned = next(role for role in roles if role["role"] == "reads-pages")[
            "models"
        ]
        self.assertEqual(
            [model["capability"] for model in assigned], ["unknown", "yes", "no"]
        )

    def test_capability_checks_warn_and_name_the_cause(self) -> None:
        operation = self.gateway["paths"]["/v1/roles"]["get"]
        description = " ".join(operation["description"].split())
        self.assertIn("effective", description)
        self.assertIn("warn", description)
        self.assertIn("never block", description)
        reason = self.schemas["ModelRoleModel"]["properties"]["reason"]
        self.assertCountEqual(reason["type"], ["string", "null"])
        self.assertIn("observed cause", " ".join(reason["description"].split()))
        response = operation["responses"]["200"]["content"]["application/json"][
            "example"
        ]
        for role in response["roles"]:
            for model in role["models"]:
                if model["capability"] == "yes":
                    self.assertIsNone(model["reason"])
                else:
                    self.assertTrue(model["reason"])

    def test_model_slots_reserve_role_names_and_reuse_slot_routing(self) -> None:
        config = self.gateway["paths"]["/v1/config"]
        description = " ".join(config["get"]["description"].split())
        self.assertIn("role:<ModelRole>", description)
        self.assertIn(ROLE_REF, description)
        self.assertIn("same slot", description)
        patch = " ".join(config["patch"]["description"].split())
        self.assertIn("role:", patch)
        self.assertIn("list of valid roles", patch)
        self.assertIn("modelSlots", patch)
        self.assertIn("404", description)
        self.assertIn("model_not_found", description)
        self.assertIn(
            "No model has the role Reads pages. Give one that role under Routing > Model roles.",
            description,
        )

    def test_models_listing_identifies_assigned_roles(self) -> None:
        model = self.schemas["Model"]
        self.assertEqual(
            model["properties"]["x_eugene_plexus"],
            {"$ref": "#/components/schemas/ModelRoutingInfo"},
        )
        routing = self.schemas["ModelRoutingInfo"]
        self.assertEqual(
            routing["properties"]["role"]["$ref"], "#/components/schemas/ModelRoleInfo"
        )
        self.assertNotIn("role", routing.get("required", []))
        info = self.schemas["ModelRoleInfo"]
        self.assertEqual(set(info["required"]), {"role", "label"})
        self.assertEqual(info["properties"]["label"]["type"], "string")
        description = " ".join(
            self.gateway["paths"]["/v1/models"]["get"]["description"].split()
        )
        self.assertIn("role:<name>", description)
        self.assertIn("x_eugene_plexus.role", description)
        self.assertIn("no models is omitted", description)


if __name__ == "__main__":
    unittest.main()
