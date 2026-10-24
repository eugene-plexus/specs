"""Gateway answer envelopes identify the machine whose runtime answered."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

CONTRACT = Path(__file__).resolve().parents[1] / "openapi" / "gateway.yaml"


class GatewayRoutingNodeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schemas = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))[
            "components"
        ]["schemas"]
        envelopes = {
            schema["properties"]["x_eugene_plexus"]["$ref"].removeprefix(
                "#/components/schemas/"
            )
            for schema in schemas.values()
            if "x_eugene_plexus" in schema.get("properties", {})
        }
        cls.routing_schemas = {
            name: schemas[name]
            for name in envelopes
            if {"driver", "runtime"} <= schemas[name].get("properties", {}).keys()
        }

    def test_every_routing_envelope_has_a_nullable_node(self) -> None:
        self.assertIn("CompletionRoutingInfo", self.routing_schemas)
        for name, schema in self.routing_schemas.items():
            with self.subTest(schema=name):
                self.assertIn("node", schema["properties"])
                self.assertCountEqual(
                    schema["properties"]["node"]["type"], ["string", "null"]
                )

    def test_node_documents_registry_identity_cloud_null_and_header(self) -> None:
        self.assertTrue(self.routing_schemas)
        for name, schema in self.routing_schemas.items():
            with self.subTest(schema=name):
                self.assertIn("node", schema["properties"])
                description = " ".join(
                    schema["properties"]["node"]["description"].split()
                )
                for phrase in (
                    "machine whose runtime answered",
                    "root's node registry",
                    "Null when the backend is not a machine's runtime",
                    "cloud provider",
                    "x_eugene_plexus",
                    "headers",
                    "x-eugene-plexus-node",
                ):
                    self.assertIn(phrase, description)


if __name__ == "__main__":
    unittest.main()
