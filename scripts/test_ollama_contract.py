"""Offline contract checks for row 65. Run directly or through pytest."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml

OPENAPI = Path(__file__).resolve().parents[1] / "openapi"


def response(operation: dict, status: str) -> dict:
    return operation["responses"][status]["content"]["application/json"]["schema"]


class OllamaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library = yaml.safe_load(
            (OPENAPI / "library.yaml").read_text(encoding="utf-8")
        )
        cls.agent = yaml.safe_load((OPENAPI / "agent.yaml").read_text(encoding="utf-8"))
        cls.schemas = cls.library["components"]["schemas"]

    def test_keep_endpoints_return_jobs(self) -> None:
        paths = self.library["paths"]
        for path in ("/v1/models/{model_id}/keep", "/v1/nodes/{node}/ollama/keep"):
            operation = paths[path]["post"]
            self.assertEqual(
                response(operation, "202"), {"$ref": "#/components/schemas/KeepJob"}
            )
            self.assertIn("409", operation["responses"])
        job = paths["/v1/keep-jobs/{id}"]
        for method in ("get", "delete"):
            self.assertEqual(
                response(job[method], "200"), {"$ref": "#/components/schemas/KeepJob"}
            )
        request = self.schemas["KeepRequest"]
        self.assertNotIn("folder", request.get("required", []))
        self.assertEqual(request["properties"]["folder"]["type"], "string")
        self.assertEqual(
            set(self.schemas["KeepJob"]["properties"]["state"]["enum"]),
            {"running", "done", "failed", "cancelled"},
        )
        self.assertEqual(
            set(self.schemas["KeepJob"]["properties"]["method"]["enum"]),
            {"link", "copy"},
        )
        self.assertEqual(
            self.schemas["KeepJob"]["properties"]["bytesDone"]["minimum"], 0
        )

    def test_kept_provenance_preserves_names(self) -> None:
        self.assertEqual(
            self.schemas["LibraryModel"]["properties"]["keptFrom"],
            {"$ref": "#/components/schemas/OllamaKept"},
        )
        kept = self.schemas["OllamaKept"]
        self.assertLessEqual(
            {"servedName", "tags", "digest", "store", "keptAt", "method"},
            set(kept["required"]),
        )
        self.assertEqual(kept["properties"]["keptAt"]["format"], "date-time")
        self.assertIn(
            "while that tag exists", self.schemas["OllamaDetail"]["description"]
        )
        self.assertIn("fingerprint", self.schemas["KeepJob"]["description"])

    def test_report_route_is_agent_owned_and_bounded(self) -> None:
        report = self.library["paths"]["/v1/nodes/{node}/ollama"]["put"]
        self.assertEqual(report["x-max-body-bytes"], 1024 * 1024)
        for status in ("403", "413"):
            self.assertIn(status, report["responses"])
        self.assertIn("sub: agent", report["description"])
        self.assertIn("node:{node}", report["description"])
        self.assertIn("2,000", report["description"])
        self.assertEqual(
            report["requestBody"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/OllamaReport"},
        )

    def test_worker_listing_is_metadata_without_a_run_identity(self) -> None:
        listing = self.library["paths"]["/v1/nodes/ollama"]["get"]
        self.assertEqual(
            response(listing, "200"), {"$ref": "#/components/schemas/NodeOllamaList"}
        )
        model = self.schemas["OllamaReportedModel"]
        self.assertLessEqual(
            {"tags", "digest", "sizeBytes", "runner"}, set(model["required"])
        )
        self.assertTrue({"id", "profiles", "fit"}.isdisjoint(model["properties"]))
        self.assertTrue(model["properties"]["libraryModel"]["readOnly"])
        self.assertEqual(
            self.schemas["OllamaReportedStore"]["properties"]["models"]["maxItems"],
            2000,
        )
        self.assertIn("error", self.schemas["OllamaReportedStore"]["properties"])

    def test_send_targets_a_keep_job_without_arbitrary_paths_or_urls(self) -> None:
        operation = self.agent["paths"]["/v1/ollama/send"]["post"]
        request = self.agent["components"]["schemas"]["OllamaSendRequest"]
        self.assertEqual(set(request["properties"]), {"job", "digest"})
        self.assertEqual(set(request["required"]), {"job", "digest"})
        self.assertFalse(request["additionalProperties"])
        self.assertIn("403", operation["responses"])
        self.assertIn("16 MiB", operation["description"])
        self.assertIn("Library's host", operation["description"])
        self.assertIn("never forwards an operator session", operation["description"])
        self.assertIn(
            "reportOllama", self.agent["paths"]["/v1/config"]["get"]["description"]
        )

    def test_keep_upload_is_job_scoped_and_checks_expected_digest(self) -> None:
        paths = self.library["paths"]
        for suffix, method in (("/state", "post"), ("", "put"), ("/complete", "post")):
            operation = paths[f"/v1/keep-jobs/{{id}}/files{suffix}"][method]
            self.assertIn("403", operation["responses"])
            self.assertIn("409", operation["responses"])
        chunk = paths["/v1/keep-jobs/{id}/files"]["put"]
        self.assertEqual(chunk["x-max-body-bytes"], 16 * 1024 * 1024)
        body = chunk["requestBody"]["content"]["application/octet-stream"]["schema"]
        self.assertEqual(body, {"type": "string", "format": "binary"})
        self.assertEqual(
            self.schemas["KeepFileRequest"]["properties"]["role"]["enum"],
            ["weights", "projector"],
        )
        self.assertIn(
            "digest", paths["/v1/keep-jobs/{id}/files/complete"]["post"]["description"]
        )

    def test_folder_listing_explains_read_only_real_paths(self) -> None:
        folders = self.schemas["LibraryFolderList"]["properties"]["folders"]
        self.assertEqual(
            folders["items"], {"$ref": "#/components/schemas/LibraryFolderStatus"}
        )
        status = self.schemas["LibraryFolderStatus"]["allOf"][1]
        self.assertTrue(status["properties"]["readOnly"]["readOnly"])
        self.assertTrue(status["properties"]["readOnlyReason"]["readOnly"])
        self.assertIn("error", status["properties"])

    def test_protocol_snapshot_carries_kept_models(self) -> None:
        snapshot = json.loads(
            (OPENAPI / "run-operations.json").read_text(encoding="utf-8")
        )
        schemas = snapshot["components"]["schemas"]
        self.assertEqual(
            schemas["LibraryModel"]["properties"]["keptFrom"],
            {
                "anyOf": [
                    {"$ref": "#/components/schemas/OllamaKept"},
                    {"type": "null"},
                ],
            },
        )
        self.assertNotIn("keptFrom", schemas["LibraryModel"]["required"])
        self.assertEqual(
            set(schemas["OllamaKept"]["required"]),
            set(self.schemas["OllamaKept"]["required"]),
        )


if __name__ == "__main__":
    unittest.main()
