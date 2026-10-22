"""Row 24: client keys rotate and record last use (contract shape)."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

OPENAPI = Path(__file__).resolve().parents[1] / "openapi"


def _load(name: str) -> dict:
    return yaml.safe_load((OPENAPI / name).read_text(encoding="utf-8"))


class ClientKeyRotateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schemas = _load("components/client-keys.yaml")["components"]["schemas"]
        cls.control = _load("control.yaml")
        cls.agent = _load("agent.yaml")

    def test_client_key_gains_rotation_fields(self) -> None:
        props = self.schemas["ClientKey"]["properties"]
        for name in ("retiresAt", "replaces", "replacedBy"):
            self.assertIn(name, props)
        self.assertEqual(props["retiresAt"]["format"], "date-time")
        self.assertIn("to the minute", props["lastUsedAt"]["description"])
        self.assertNotIn("Reserved", props["lastUsedAt"]["description"])

    def test_rotate_request_bounds(self) -> None:
        request = self.schemas["ClientKeyRotateRequest"]
        self.assertIs(request["additionalProperties"], False)
        overlap = request["properties"]["overlapSeconds"]
        self.assertEqual(overlap["minimum"], 0)
        self.assertEqual(overlap["maximum"], 2592000)
        self.assertEqual(overlap["default"], 86400)
        ttl = request["properties"]["ttlDays"]
        self.assertEqual(ttl["minimum"], 1)
        self.assertNotIn("default", ttl)

    def test_policy_entry_is_unchanged(self) -> None:
        entry = self.schemas["ClientKeyPolicyEntry"]
        self.assertIs(entry["additionalProperties"], False)
        self.assertEqual(set(entry["properties"]), {"id", "expiresAt", "revokedAt"})

    def test_log_page_names_the_new_ops(self) -> None:
        schemas = self.control["components"]["schemas"]
        ops = [
            value
            for schema in schemas.values()
            if isinstance(schema, dict)
            for value in (schema.get("properties", {}).get("op", {}).get("enum") or [])
        ]
        self.assertIn("rotateClientKey", ops)
        self.assertIn("touchClientKey", ops)

    def test_rotate_paths(self) -> None:
        for doc in (self.control, self.agent):
            op = doc["paths"]["/v1/auth/client-keys/{keyId}/rotate"]["post"]
            self.assertEqual(op["operationId"], "rotateClientKey")
            self.assertIn("201", op["responses"])
            for code in ("404", "409", "503"):
                self.assertIn(code, op["responses"])
            body = op["requestBody"]["content"]["application/json"]["schema"]
            self.assertTrue(body["$ref"].endswith("ClientKeyRotateRequest"))
            ok = op["responses"]["201"]["content"]["application/json"]["schema"]
            self.assertTrue(ok["$ref"].endswith("ClientKeyCreated"))


if __name__ == "__main__":
    unittest.main()
