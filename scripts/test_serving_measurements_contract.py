"""Row 10's serving records remain usable by later capacity and routing rows.

Run with unittest or pytest using a Python with PyYAML installed.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

OPENAPI = Path(__file__).resolve().parents[1] / "openapi"
BASE = "/v1/serving-measurements"
PROBLEM = "components/common.yaml#/components/responses/Problem"


def schema_ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


class ServingMeasurementsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.agent = yaml.safe_load((OPENAPI / "agent.yaml").read_text(encoding="utf-8"))
        cls.schemas = cls.agent["components"]["schemas"]
        cls.paths = cls.agent["paths"]

    def response_schema(self, operation: dict, status: str) -> dict:
        return operation["responses"][status]["content"]["application/json"]["schema"]

    def test_measurement_jobs_have_list_start_preflight_and_cancel_doors(self) -> None:
        cases = (
            (BASE, "get", "listServingMeasurements", "200", "ServingMeasurementList"),
            (BASE, "post", "startServingMeasurement", "202", "ServingMeasurement"),
            (
                f"{BASE}/preflight",
                "post",
                "preflightServingMeasurement",
                "200",
                "ServingMeasurementPreflight",
            ),
            (
                f"{BASE}/{{id}}/cancel",
                "post",
                "cancelServingMeasurement",
                "200",
                "ServingMeasurement",
            ),
        )
        for path, method, operation_id, status, result in cases:
            with self.subTest(operation=operation_id):
                operation = self.paths[path][method]
                self.assertEqual(operation["operationId"], operation_id)
                self.assertEqual(
                    self.response_schema(operation, status), schema_ref(result)
                )
                self.assertIn("Operator-only", operation["description"])
                self.assertEqual(operation["responses"]["401"], {"$ref": PROBLEM})
        for path in (BASE, f"{BASE}/preflight"):
            body = self.paths[path]["post"]["requestBody"]
            self.assertTrue(body["required"])
            self.assertEqual(
                body["content"]["application/json"]["schema"],
                schema_ref("ServingMeasurementRequest"),
            )
        cancel = self.paths[f"{BASE}/{{id}}/cancel"]["post"]
        self.assertIn(
            {
                "name": "id",
                "in": "path",
                "required": True,
                "schema": {"type": "string", "minLength": 1},
            },
            cancel["parameters"],
        )

    def test_listing_can_filter_by_runtime_and_keeps_completed_evidence(self) -> None:
        operation = self.paths[BASE]["get"]
        self.assertIn(
            {
                "name": "runtime",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "minLength": 1},
            },
            operation["parameters"],
        )
        description = " ".join(operation["description"].split())
        for phrase in (
            "newest 20",
            "newest completed",
            "per runtime",
            "across agent restarts",
        ):
            self.assertIn(phrase, description)
        listing = self.schemas["ServingMeasurementList"]
        self.assertEqual(listing["required"], ["measurements"])
        self.assertEqual(
            listing["properties"]["measurements"]["items"],
            schema_ref("ServingMeasurement"),
        )
        self.assertNotIn("maxItems", listing["properties"]["measurements"])

    def test_request_defaults_are_seeded_and_resolve_against_the_runtime(self) -> None:
        request = self.schemas["ServingMeasurementRequest"]
        self.assertEqual(request["required"], ["runtime"])
        self.assertFalse(request["additionalProperties"])
        fields = request["properties"]
        self.assertEqual(fields["runtime"]["type"], "string")
        self.assertEqual(fields["workload"]["default"], "agents")
        self.assertEqual(
            fields["workload"]["$ref"], "#/components/schemas/ServingWorkload"
        )
        self.assertEqual(
            self.schemas["ServingWorkload"]["enum"], ["agents", "chat", "streams"]
        )
        for name, minimum, maximum in (
            ("maxPeople", 1, 256),
            ("windowSeconds", 10, 3600),
        ):
            self.assertEqual(fields[name]["type"], "integer")
            self.assertEqual(fields[name]["minimum"], minimum)
            self.assertEqual(fields[name]["maximum"], maximum)
            self.assertNotIn(
                "default",
                fields[name],
                "a constant default would hide the effective value",
            )
        self.assertIn("parallelSlots", fields["maxPeople"]["description"])
        for value in ("300", "120", "3,600"):
            self.assertIn(value, fields["windowSeconds"]["description"])
        self.assertIs(fields["full"]["default"], False)
        self.assertEqual(fields["seed"]["type"], "integer")
        self.assertEqual(fields["seed"]["default"], 0)
        effective = self.schemas["ServingMeasurement"]["properties"]["request"]
        self.assertEqual(
            effective["$ref"], "#/components/schemas/ServingMeasurementRequest"
        )
        self.assertIn("effective", effective["description"])

    def test_troys_knee_thresholds_have_expert_overrides(self) -> None:
        fields = self.schemas["ServingMeasurementRequest"]["properties"]
        ttft = fields["ttftThresholdMs"]
        self.assertEqual(ttft["default"], 1000)
        self.assertEqual(ttft["exclusiveMinimum"], 0)
        speed = fields["speedRatioThreshold"]
        self.assertAlmostEqual(speed["default"], 2 / 3)
        self.assertEqual(speed["exclusiveMinimum"], 0)
        self.assertEqual(speed["maximum"], 1)
        description = " ".join(self.schemas["ServingKnee"]["description"].split())
        self.assertIn("ttftThresholdMs", description)
        self.assertIn("speedRatioThreshold", description)
        self.assertIn("last level before", description)

    def test_preflight_names_replicas_without_stopping_them(self) -> None:
        preflight = self.schemas["ServingMeasurementPreflight"]
        self.assertLessEqual(
            {"otherReplicas", "otherRuntimes", "problems", "estimateSeconds"},
            set(preflight["required"]),
        )
        for name in ("otherReplicas", "otherRuntimes"):
            self.assertEqual(
                preflight["properties"][name]["items"], schema_ref("ServingRuntime")
            )
        self.assertEqual(
            set(self.schemas["ServingRuntime"]["required"]),
            {"node", "runtime", "model"},
        )
        estimate = preflight["properties"]["estimateSeconds"]
        self.assertCountEqual(estimate["type"], ["integer", "null"])
        description = " ".join(
            self.paths[f"{BASE}/preflight"]["post"]["description"].split()
        )
        for phrase in (
            "Changes nothing",
            "caller",
            "consent",
            "unknown",
            "never block",
        ):
            self.assertIn(phrase, description)
        start = " ".join(self.paths[BASE]["post"]["description"].split())
        self.assertIn("409", start)
        self.assertIn("other ready replicas", start)
        consent = self.schemas["ServingMeasurementRequest"]["properties"][
            "stopReplicas"
        ]
        self.assertEqual(consent["default"], [])
        self.assertEqual(consent["items"], schema_ref("ServingRuntime"))
        self.assertIn("agreed", consent["description"])
        self.assertIn("Already stopped", consent["description"])

    def test_measurement_key_is_local_scoped_memory_only_and_revoked_at_run_end(
        self,
    ) -> None:
        description = " ".join(self.paths[BASE]["post"]["description"].split())
        for phrase in (
            "caller",
            "localOnly",
            "allowedModels: [alias]",
            "64",
            "10,000",
            "ttlDays: 1",
            "memory",
            "cloud",
            "fallback",
            "revoked when the run ends",
        ):
            self.assertIn(phrase, description)
        cancel = " ".join(
            self.paths[f"{BASE}/{{id}}/cancel"]["post"]["description"].split()
        )
        for phrase in ("caller", "finished", "keyLive", "revok"):
            self.assertIn(phrase, cancel)
        record = self.schemas["ServingMeasurement"]
        self.assertEqual(record["properties"]["keyLive"]["type"], "boolean")
        self.assertFalse(
            {"credential", "clientKey", "token", "apiKey"} & set(record["properties"])
        )

    def test_result_preserves_the_shared_record_and_partial_results(self) -> None:
        record = self.schemas["ServingMeasurement"]
        expected = {
            "id",
            "node",
            "runtime",
            "model",
            "state",
            "request",
            "startedAt",
            "finishedAt",
            "progress",
            "detail",
            "levels",
            "knee",
            "provenance",
            "provenanceKey",
            "current",
            "staleBecause",
            "keyLive",
            "restarts",
        }
        self.assertLessEqual(expected, set(record["required"]))
        fields = record["properties"]
        self.assertEqual(fields["state"], schema_ref("BenchmarkState"))
        self.assertEqual(fields["levels"]["items"], schema_ref("ServingLevel"))
        self.assertCountEqual(fields["finishedAt"]["type"], ["string", "null"])
        self.assertEqual(fields["startedAt"]["format"], "date-time")
        self.assertEqual(fields["finishedAt"]["format"], "date-time")
        self.assertEqual(fields["progress"]["minimum"], 0)
        self.assertEqual(fields["progress"]["maximum"], 1)
        self.assertEqual(
            fields["knee"]["anyOf"], [schema_ref("ServingKnee"), {"type": "null"}]
        )
        self.assertEqual(
            set(self.schemas["ServingKnee"]["required"]),
            {"found", "people", "tokensPerSecondEach", "ttftP50Ms"},
        )
        self.assertIn("observed cause", fields["detail"]["description"])
        description = " ".join(record["description"].split())
        self.assertIn("restart", description)
        self.assertIn("failed", description)
        self.assertIn("partial", description)

    def test_levels_keep_the_curve_counts_and_unknown_readings_distinct(self) -> None:
        level = self.schemas["ServingLevel"]
        expected = {
            "people",
            "streamsMean",
            "streamsPeak",
            "requests",
            "errors",
            "errorCauses",
            "ttftP50Ms",
            "ttftP90Ms",
            "itlP50Ms",
            "itlP90Ms",
            "tokensPerSecondEachP50",
            "tokensPerSecondEachP10",
            "tokensPerSecondTotal",
            "promptTokens",
            "cachedTokens",
            "waitedP50Ms",
            "foreignRequests",
            "watts",
        }
        self.assertLessEqual(expected, set(level["required"]))
        fields = level["properties"]
        for name in (
            "ttftP50Ms",
            "ttftP90Ms",
            "itlP50Ms",
            "itlP90Ms",
            "tokensPerSecondEachP50",
            "tokensPerSecondEachP10",
            "waitedP50Ms",
            "watts",
        ):
            with self.subTest(reading=name):
                self.assertCountEqual(fields[name]["type"], ["number", "null"])
                self.assertEqual(fields[name]["minimum"], 0)
        self.assertCountEqual(fields["foreignRequests"]["type"], ["integer", "null"])
        self.assertIn("unknown", fields["foreignRequests"]["description"])
        self.assertEqual(
            fields["errorCauses"]["additionalProperties"],
            {"type": "integer", "minimum": 1},
        )
        for name in (
            "requests",
            "errors",
            "promptTokens",
            "cachedTokens",
            "outputTokens",
        ):
            self.assertEqual(fields[name]["type"], "integer")
            self.assertEqual(fields[name]["minimum"], 0)
        self.assertIn("outputTokens", level["required"])
        self.assertIn("durationSeconds", level["required"])
        self.assertEqual(fields["promptReuse"]["maximum"], 1)
        self.assertIn("50 ms", fields["loopLagged"]["description"])

    def test_provenance_is_typed_and_covers_every_staleness_input(self) -> None:
        provenance = self.schemas["ServingProvenance"]
        expected = {
            "engine",
            "engineBuild",
            "binaryHash",
            "launchArgv",
            "modelPath",
            "modelSizeBytes",
            "modelModifiedAt",
            "gpus",
            "driver",
            "cpu",
            "ramBytes",
            "agentCommit",
            "gatewayCommit",
        }
        self.assertEqual(set(provenance["required"]), expected)
        self.assertEqual(set(provenance["properties"]), expected)
        self.assertEqual(
            provenance["properties"]["launchArgv"]["items"], {"type": "string"}
        )
        self.assertEqual(
            provenance["properties"]["gpus"]["items"], schema_ref("ServingGpu")
        )
        fields = self.schemas["ServingMeasurement"]["properties"]
        self.assertEqual(fields["provenance"], schema_ref("ServingProvenance"))
        self.assertEqual(fields["provenanceKey"]["pattern"], "^[0-9a-f]{64}$")
        self.assertIn("sha256", fields["provenanceKey"]["description"])
        self.assertIn("on read", fields["current"]["description"])
        self.assertEqual(fields["staleBecause"]["items"], {"type": "string"})
        self.assertIn("changed", fields["staleBecause"]["description"])

    def test_drafting_and_replica_restarts_are_readable_across_nodes(self) -> None:
        fields = self.schemas["ServingMeasurement"]["properties"]
        self.assertEqual(fields["drafting"], schema_ref("ServingDrafting"))
        drafting = self.schemas["ServingDrafting"]
        self.assertEqual(set(drafting["required"]), {"type", "model", "acceptance"})
        self.assertCountEqual(
            drafting["properties"]["acceptance"]["type"], ["number", "null"]
        )
        self.assertEqual(drafting["properties"]["acceptance"]["maximum"], 1)
        self.assertEqual(
            fields["restarts"]["items"], schema_ref("ServingMeasurementRestart")
        )
        restart = self.schemas["ServingMeasurementRestart"]
        self.assertEqual(
            set(restart["required"]), {"node", "runtime", "state", "detail"}
        )
        self.assertEqual(
            restart["properties"]["state"], schema_ref("MeasurementRestartState")
        )

    def test_failures_and_runtime_identity_checks_name_the_observed_cause(self) -> None:
        operation = self.paths[BASE]["post"]
        for status in ("400", "403", "404", "409", "422", "503"):
            self.assertEqual(operation["responses"][status], {"$ref": PROBLEM})
        description = " ".join(operation["description"].split())
        for phrase in (
            "X-Eugene-Plexus-Runtime",
            "observed cause",
            "5%",
            "60 s",
            "in flight",
            "one level past",
            "another runtime",
        ):
            self.assertIn(phrase, description)


if __name__ == "__main__":
    unittest.main()
