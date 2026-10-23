"""Row 68 distinguishes an available template from the one actually in use."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

OPENAPI = Path(__file__).resolve().parents[1] / "openapi"
FALLBACK_REF = "#/components/schemas/ChatTemplateFallback"
RUNTIME_REF = "#/components/schemas/RuntimeChatTemplate"


class DeepSeekFlashContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.documents = {
            name: yaml.safe_load((OPENAPI / name).read_text(encoding="utf-8"))
            for name in ("library.yaml", "agent.yaml", "components/common.yaml")
        }
        cls.library = cls.documents["library.yaml"]["components"]["schemas"]
        cls.agent = cls.documents["agent.yaml"]["components"]["schemas"]
        cls.registry = Registry().with_resources(
            (
                (OPENAPI / name).as_uri(),
                Resource.from_contents(document, default_specification=DRAFT202012),
            )
            for name, document in cls.documents.items()
        )

    def validator(self, document: str, schema: str) -> Draft202012Validator:
        return Draft202012Validator(
            {"$ref": f"{(OPENAPI / document).as_uri()}#/components/schemas/{schema}"},
            registry=self.registry,
            format_checker=FormatChecker(),
        )

    def test_local_and_preflight_fallbacks_are_optional_read_only_observations(
        self,
    ) -> None:
        for name in ("GgufDetail", "CataloguePreflight"):
            with self.subTest(schema=name):
                schema = self.library[name]
                field = schema["properties"]["chatTemplateFallback"]
                self.assertEqual(field["$ref"], FALLBACK_REF)
                self.assertIs(field["readOnly"], True)
                self.assertNotIn("chatTemplateFallback", schema.get("required", []))
                self.assertNotIn("default", field)

    def test_fallback_names_its_template_engines_and_review_source(self) -> None:
        schema = self.library["ChatTemplateFallback"]
        self.assertEqual(
            set(schema["required"]), {"id", "name", "engines", "sourceUrl"}
        )
        for field in ("id", "name"):
            with self.subTest(field=field):
                self.assertEqual(schema["properties"][field]["type"], "string")
                self.assertEqual(schema["properties"][field]["minLength"], 1)
        engines = schema["properties"]["engines"]
        self.assertEqual(engines["type"], "array")
        self.assertEqual(engines["minItems"], 1)
        self.assertIs(engines["uniqueItems"], True)
        self.assertEqual(
            engines["items"]["$ref"],
            "components/common.yaml#/components/schemas/EngineKind",
        )
        self.assertEqual(schema["properties"]["sourceUrl"]["format"], "uri")

    def test_fallback_requires_header_evidence_and_does_not_gate_an_engine(
        self,
    ) -> None:
        description = " ".join(
            self.library["ChatTemplateFallback"]["description"].split()
        )
        for rule in (
            "header confirms",
            "no embedded chat template",
            "not the template in effect",
            "eligibility",
            "does not block",
            "override",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, description)
        embedded = self.library["ModelCapabilities"]["properties"]["chatTemplate"]
        self.assertEqual(embedded["type"], "boolean")
        self.assertIn("file embeds", embedded["description"])
        self.assertIn("chatTemplateFallback", embedded["description"])

    def test_fallback_examples_validate_and_cannot_hide_missing_provenance(
        self,
    ) -> None:
        schema = self.library["ChatTemplateFallback"]
        validator = self.validator("library.yaml", "ChatTemplateFallback")
        example = schema["example"]
        validator.validate(example)
        for field in schema["required"]:
            with self.subTest(missing=field):
                incomplete = {
                    key: value for key, value in example.items() if key != field
                }
                self.assertFalse(validator.is_valid(incomplete))
        for engines in ([], ["llama_cpp", "llama_cpp"], ["invented-engine"]):
            with self.subTest(engines=engines):
                self.assertFalse(validator.is_valid({**example, "engines": engines}))
        for source_url in ("", None, 42):
            with self.subTest(sourceUrl=source_url):
                self.assertFalse(
                    validator.is_valid({**example, "sourceUrl": source_url})
                )

    def test_runtime_template_is_optional_read_only_and_not_declarable(self) -> None:
        runtime = self.agent["Runtime"]
        field = runtime["properties"]["chatTemplate"]
        self.assertEqual(field["$ref"], RUNTIME_REF)
        self.assertIs(field["readOnly"], True)
        self.assertNotIn("chatTemplate", runtime["required"])
        self.assertNotIn("default", field)
        self.assertNotIn("chatTemplate", self.agent["RuntimeSpec"]["properties"])

    def test_effective_template_has_identity_and_no_assumed_source(self) -> None:
        schema = self.agent["RuntimeChatTemplate"]
        self.assertEqual(set(schema["required"]), {"source", "name", "sha256"})
        source = schema["properties"]["source"]
        self.assertEqual(source["type"], "string")
        self.assertCountEqual(
            source["enum"], ["embedded", "eugene", "override", "engine"]
        )
        self.assertNotIn("default", source)
        self.assertEqual(schema["properties"]["sha256"]["pattern"], "^[0-9a-f]{64}$")
        for field in ("id", "name", "path"):
            with self.subTest(field=field):
                self.assertEqual(schema["properties"][field]["type"], "string")
                self.assertEqual(schema["properties"][field]["minLength"], 1)
        self.assertNotIn("id", schema["required"])
        self.assertNotIn("path", schema["required"])

    def test_runtime_template_requires_engine_confirmation_and_clears_on_stop(
        self,
    ) -> None:
        schema = self.agent["RuntimeChatTemplate"]
        description = " ".join(schema["description"].split())
        for rule in (
            "engine reports",
            "UTF-8",
            "stopped",
            "unconfirmed",
            "not inferred from argv",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, description)
        source = schema["properties"]["source"]["description"]
        for origin in ("embedded", "eugene", "override", "engine"):
            with self.subTest(origin=origin):
                self.assertIn(f"`{origin}`", source)
        self.assertIn("match", source)
        self.assertIn("unknown", source)
        self.assertIn(
            "ChatTemplateFallback.id", schema["properties"]["id"]["description"]
        )

    def test_runtime_examples_validate_and_reject_unproved_or_bad_identity(
        self,
    ) -> None:
        schema = self.agent["RuntimeChatTemplate"]
        validator = self.validator("agent.yaml", "RuntimeChatTemplate")
        example = schema["example"]
        validator.validate(example)
        for source in schema["properties"]["source"]["enum"]:
            with self.subTest(source=source):
                validator.validate(
                    {"source": source, "name": "Template", "sha256": "a" * 64}
                )
        for field in schema["required"]:
            with self.subTest(missing=field):
                incomplete = {
                    key: value for key, value in example.items() if key != field
                }
                self.assertFalse(validator.is_valid(incomplete))
        for changed in (
            {"source": "auto"},
            {"name": ""},
            {"sha256": "unconfirmed"},
            {"sha256": "A" * 64},
            {"id": ""},
            {"path": ""},
        ):
            with self.subTest(changed=changed):
                self.assertFalse(validator.is_valid({**example, **changed}))

    def test_old_responses_still_validate_without_template_observations(self) -> None:
        self.validator("library.yaml", "GgufDetail").validate({})
        self.validator("library.yaml", "CataloguePreflight").validate(
            {
                "repo": "example/model",
                "file": "model.gguf",
                "format": "gguf",
                "bytesRead": 32,
            }
        )
        self.validator("agent.yaml", "Runtime").validate(
            {
                "name": "old",
                "engine": "llama_cpp",
                "modelPath": "/model.gguf",
                "status": "stopped",
            }
        )

    def test_ci_runs_the_deepseek_flash_contract_checks(self) -> None:
        workflow = yaml.safe_load(
            (OPENAPI.parent / ".github" / "workflows" / "ci.yml").read_text(
                encoding="utf-8"
            )
        )
        commands = [
            step.get("run") for step in workflow["jobs"]["validate-openapi"]["steps"]
        ]
        self.assertIn("python scripts/test_deepseek_flash_contract.py", commands)


if __name__ == "__main__":
    unittest.main()
