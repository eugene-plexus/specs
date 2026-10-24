"""Folder access exposes recorded rights and keeps privilege changes scoped."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, ClassVar

import yaml

CONTRACT = Path(__file__).resolve().parents[1] / "openapi" / "agent.yaml"
BASE = "/v1/apps/{app}/folder-access"
PROBLEM = "components/common.yaml#/components/schemas/Problem"


class FolderAccessContractTests(unittest.TestCase):
    document: ClassVar[dict[str, Any]]
    paths: ClassVar[dict[str, Any]]
    schemas: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.document = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        cls.paths = cls.document["paths"]
        cls.schemas = cls.document["components"]["schemas"]

    def test_operator_routes_and_auth_failures(self) -> None:
        for path, method, operation_id in (
            (BASE, "get", "listFolderAccess"),
            (BASE, "post", "addFolderAccess"),
            (BASE + "/{id}", "delete", "removeFolderAccess"),
            (BASE + "/{id}/unknown/{entry}", "post", "decideFolderAccessEntry"),
        ):
            with self.subTest(operation=operation_id):
                item = self.paths[path]
                parameters = item["parameters"]
                self.assertIn(
                    {"$ref": "#/components/parameters/FolderAccessApp"}, parameters
                )
                operation = item[method]
                self.assertEqual(operation["operationId"], operation_id)
                self.assertEqual(operation["security"], [{"bearerAuth": []}])
                description = " ".join(operation["description"].split())
                self.assertIn("operator session", description)
                self.assertIn("service token", description)
                self.assertIn("gateway token", description)
                self.assertIn("client key", description)
                for status in ("401", "403", "404"):
                    response = operation["responses"][status]
                    self.assertIn("application/problem+json", response["content"])
        app = self.document["components"]["parameters"]["FolderAccessApp"]
        self.assertEqual(
            (app["in"], app["name"], app["required"]), ("path", "app", True)
        )
        self.assertEqual(app["schema"]["pattern"], "^[a-z][a-z0-9-]{1,39}$")
        grant = self.paths[BASE + "/{id}"]["parameters"][1]
        self.assertEqual(
            (grant["in"], grant["name"], grant["required"]), ("path", "id", True)
        )

    def test_release_requires_own_app_key_and_never_adds_access(self) -> None:
        operation = self.paths[BASE + "/release"]["post"]
        self.assertEqual(operation["operationId"], "releaseFolderAccess")
        self.assertEqual(operation["security"], [{"bearerAuth": []}])
        description = " ".join(operation["description"].split())
        for boundary in (
            "app:<app>@<this node>",
            "no other grant names the folder",
            "only what Eugene added",
            "never adds",
            "another app",
            "operator session",
            "service token",
            "gateway token",
        ):
            self.assertIn(boundary, description)
        self.assertEqual(
            operation["requestBody"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/FolderAccessReleaseRequest"},
        )
        self.assertTrue(operation["requestBody"]["required"])
        for status in ("401", "403", "409", "500"):
            self.assertIn(
                "application/problem+json", operation["responses"][status]["content"]
            )
        self.assertEqual(
            operation["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/FolderAccessList"},
        )
        self.assertIn("no recorded access", description)

    def test_add_is_async_and_list_reports_persisted_grants(self) -> None:
        add = self.paths[BASE]["post"]
        self.assertTrue(add["requestBody"]["required"])
        self.assertEqual(
            add["requestBody"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/FolderAccessRequest"},
        )
        self.assertEqual(
            add["responses"]["202"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/FolderAccess"},
        )
        unsafe = add["responses"]["422"]
        self.assertIn("masked", unsafe["description"])
        self.assertIn("parent", unsafe["description"])
        self.assertIn("application/problem+json", unsafe["content"])
        listing = self.paths[BASE]["get"]
        self.assertIn("agent restart", " ".join(listing["description"].split()))
        self.assertEqual(
            listing["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/FolderAccessList"},
        )
        grants = self.schemas["FolderAccessList"]
        self.assertEqual(grants["required"], ["grants"])
        self.assertEqual(grants["properties"]["grants"]["type"], "array")
        self.assertEqual(
            grants["properties"]["grants"]["items"],
            {"$ref": "#/components/schemas/FolderAccess"},
        )

    def test_requests_bound_paths_and_default_to_read(self) -> None:
        for name in ("FolderAccessRequest",):
            with self.subTest(schema=name):
                request = self.schemas[name]
                self.assertEqual(request["type"], "object")
                self.assertFalse(request["additionalProperties"])
                self.assertEqual(request["required"], ["path"])
                path = request["properties"]["path"]
                self.assertEqual(path["type"], "string")
                self.assertEqual((path["minLength"], path["maxLength"]), (1, 4096))
        request = self.schemas["FolderAccessRequest"]
        self.assertEqual(set(request["properties"]), {"path", "mode"})
        mode = request["properties"]["mode"]
        self.assertEqual(mode["enum"], ["read", "write"])
        self.assertEqual(mode["default"], "read")
        self.assertEqual(
            set(self.schemas["FolderAccessReleaseRequest"]["properties"]),
            {"path", "id"},
        )
        release = self.schemas["FolderAccessReleaseRequest"]
        self.assertIn("Exactly one", release["description"])
        self.assertEqual((release["minProperties"], release["maxProperties"]), (1, 1))

    def test_records_require_effective_state_and_provenance(self) -> None:
        record = self.schemas["FolderAccess"]
        expected = {
            "id": "string",
            "app": "string",
            "path": "string",
            "mode": "string",
            "account": "string",
            "state": "string",
            "preexisting": "boolean",
            "notInheriting": "integer",
            "restartNeeded": "boolean",
            "message": "string",
            "addedAt": "string",
            "addedBy": "string",
        }
        self.assertEqual(set(record["required"]), set(expected))
        for field, field_type in expected.items():
            with self.subTest(field=field):
                self.assertEqual(record["properties"][field]["type"], field_type)
        fields = record["properties"]
        self.assertEqual(fields["mode"]["enum"], ["read", "write"])
        self.assertEqual(
            fields["state"]["enum"],
            [
                "applying",
                "ready",
                "removing",
                "removed",
                "changed_outside",
                "failed",
                "incomplete",
            ],
        )
        self.assertEqual(fields["notInheriting"]["minimum"], 0)
        self.assertEqual(fields["addedAt"]["format"], "date-time")
        self.assertIn("observed cause", fields["message"]["description"])
        self.assertIn("effective", fields["state"]["description"])
        self.assertIn("restart", fields["restartNeeded"]["description"])
        self.assertIn("nothing added", fields["preexisting"]["description"])

    def test_remove_preserves_preexisting_and_changed_permissions(self) -> None:
        operation = self.paths[BASE + "/{id}"]["delete"]
        description = " ".join(operation["description"].split())
        for boundary in (
            "only what Eugene added",
            "preexisting",
            "identity",
            "changed_outside",
            "change nothing",
        ):
            self.assertIn(boundary, description)
        self.assertEqual(
            operation["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/FolderAccess"},
        )

    def test_unknown_entries_wait_for_the_owner(self) -> None:
        """R23-UNKNOWN (Troy, 2026-10-24): access Eugene did not add is the owner's call."""
        fields = self.schemas["FolderAccess"]["properties"]
        self.assertEqual(
            fields["unknown"],
            {
                "type": "array",
                "items": {"$ref": "#/components/schemas/FolderAccessUnknown"},
                "description": fields["unknown"]["description"],
            },
        )
        self.assertIn("incomplete", fields["state"]["description"].lower())
        unknown = self.schemas["FolderAccessUnknown"]
        self.assertEqual(
            set(unknown["required"]), {"id", "path", "kind", "entry", "decision"}
        )
        # Named enums, so a later inline enum cannot rename them.
        self.assertEqual(
            unknown["properties"]["kind"],
            {"$ref": "#/components/schemas/FolderAccessUnknownKind"},
        )
        self.assertEqual(
            self.schemas["FolderAccessUnknownKind"]["enum"],
            ["entry", "null_dacl", "owner", "unreadable", "hardlink"],
        )
        self.assertEqual(
            self.schemas["FolderAccessUnknownDecision"]["enum"], ["pending", "kept"]
        )
        decision = self.schemas["FolderAccessDecision"]
        self.assertEqual(decision["required"], ["action"])
        self.assertEqual(
            self.schemas["FolderAccessDecisionAction"]["enum"], ["remove", "keep"]
        )
        item = self.paths[BASE + "/{id}/unknown/{entry}"]
        self.assertEqual(
            [(p.get("name"), p.get("in")) for p in item["parameters"][1:]],
            [("id", "path"), ("entry", "path")],
        )
        operation = item["post"]
        self.assertEqual(
            operation["requestBody"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/FolderAccessDecision"},
        )
        self.assertEqual(
            operation["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/FolderAccess"},
        )
        description = " ".join(operation["description"].split())
        for boundary in ("checks the entry again", "Keep", "Remove"):
            self.assertIn(boundary, description)
        self.assertIn("application/problem+json", operation["responses"]["409"]["content"])

    def test_refusals_are_problem_responses_with_observed_causes(self) -> None:
        refusal = self.schemas["FolderAccessRefusal"]
        self.assertEqual(refusal["type"], "string")
        self.assertEqual(
            refusal["enum"],
            [
                "not_a_folder",
                "link",
                "drive_root",
                "network",
                "system",
                "eugene",
                "home",
                "unsafe_parent",
                "unavailable",
            ],
        )
        problem = self.schemas["FolderAccessProblem"]
        self.assertEqual(problem["allOf"][0], {"$ref": PROBLEM})
        extension = problem["allOf"][1]
        self.assertEqual(set(extension["required"]), {"refusal", "detail"})
        self.assertEqual(
            extension["properties"]["refusal"],
            {"$ref": "#/components/schemas/FolderAccessRefusal"},
        )
        self.assertEqual(extension["properties"]["detail"]["minLength"], 1)
        add = self.paths[BASE]["post"]
        response = add["responses"]["400"]["content"]["application/problem+json"]
        self.assertEqual(
            response["schema"], {"$ref": "#/components/schemas/FolderAccessProblem"}
        )
        self.assertEqual(
            set(response["examples"]), set(refusal["enum"]) - {"unavailable"}
        )
        for cause, example in response["examples"].items():
            with self.subTest(refusal=cause):
                self.assertEqual(example["value"]["refusal"], cause)
                self.assertEqual(example["value"]["status"], 400)
                self.assertTrue(example["value"]["detail"])
        description = " ".join(add["description"].split())
        for boundary in (
            "without following links",
            "contains a refused folder",
            "Job Site",
        ):
            self.assertIn(boundary, description)

    def test_shared_account_is_unavailable(self) -> None:
        for path, method in (
            (BASE, "get"),
            (BASE, "post"),
            (BASE + "/{id}", "delete"),
            (BASE + "/release", "post"),
        ):
            with self.subTest(path=path, method=method):
                response = self.paths[path][method]["responses"]["409"]
                content = response["content"]["application/problem+json"]
                self.assertEqual(
                    content["schema"],
                    {"$ref": "#/components/schemas/FolderAccessProblem"},
                )
                example = content["examples"]["unavailable"]["value"]
                self.assertEqual(example["refusal"], "unavailable")
                self.assertEqual(example["status"], 409)
                self.assertIn("Eugene's own account", example["detail"])
                self.assertIn(
                    "Windows service or a Linux system install", example["detail"]
                )

    def test_client_key_documentation_includes_release(self) -> None:
        security = self.document["components"]["securitySchemes"]["bearerAuth"]
        self.assertIn("client key", security["description"])
        logs = self.paths["/v1/logs"]["post"]["description"]
        self.assertIn("folder-access/release", logs)
        self.assertNotIn("the one path on the agent", logs)

    def test_contract_check_runs_in_ci(self) -> None:
        workflow = CONTRACT.parents[1] / ".github" / "workflows" / "ci.yml"
        steps = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"][
            "validate-openapi"
        ]["steps"]
        self.assertIn(
            "python scripts/test_folder_access_contract.py",
            [step.get("run") for step in steps],
        )


if __name__ == "__main__":
    unittest.main()
