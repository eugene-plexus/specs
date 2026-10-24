"""Offline contract checks for row 58, before consumer regeneration."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

OPENAPI = Path(__file__).resolve().parents[1] / "openapi"


class GeminiDoorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gateway = yaml.safe_load(
            (OPENAPI / "gateway.yaml").read_text(encoding="utf-8")
        )
        cls.driver = yaml.safe_load(
            (OPENAPI / "inference-driver.yaml").read_text(encoding="utf-8")
        )
        cls.schemas = cls.gateway["components"]["schemas"]

    def operation(self, suffix: str, method: str = "post") -> dict:
        return self.gateway["paths"][f"/v1beta/models{suffix}"][method]

    def test_both_api_versions_expose_the_five_sdk_operations(self) -> None:
        ids = set()
        for version in ("v1beta", "v1"):
            for suffix, method in (
                ("/{model}:generateContent", "post"),
                ("/{model}:streamGenerateContent", "post"),
                ("/{model}:countTokens", "post"),
                ("", "get"),
                ("/{model}", "get"),
            ):
                with self.subTest(version=version, suffix=suffix):
                    path = self.gateway["paths"][f"/{version}/models{suffix}"]
                    op = path[method]
                    self.assertNotIn(op["operationId"], ids)
                    ids.add(op["operationId"])
                    self.assertIn("200", op["responses"])
                    if "{model}" in suffix:
                        parameter = next(
                            p
                            for p in path.get("parameters", [])
                            + op.get("parameters", [])
                            if p["name"] == "model"
                        )
                        self.assertEqual(parameter["in"], "path")
                        self.assertTrue(parameter["required"])

    def test_gemini_credentials_are_alternatives_and_query_keys_are_redacted(
        self,
    ) -> None:
        schemes = self.gateway["components"]["securitySchemes"]
        for name, location, key in (
            ("geminiApiKeyAuth", "header", "x-goog-api-key"),
            ("geminiQueryKeyAuth", "query", "key"),
        ):
            self.assertEqual(schemes[name]["type"], "apiKey")
            self.assertEqual(schemes[name]["in"], location)
            self.assertEqual(schemes[name]["name"], key)
        for version in ("v1beta", "v1"):
            for path, item in self.gateway["paths"].items():
                if not path.startswith(f"/{version}/models"):
                    continue
                for method in ("get", "post"):
                    if method in item:
                        self.assertEqual(
                            item[method]["security"],
                            [
                                {"bearerAuth": []},
                                {"geminiApiKeyAuth": []},
                                {"geminiQueryKeyAuth": []},
                            ],
                        )
        description = " ".join(schemes["geminiQueryKeyAuth"]["description"].split())
        self.assertIn("every log", description)
        self.assertIn("metrics", description)

    def test_generation_maps_contents_tools_search_and_settings(self) -> None:
        op = self.operation("/{model}:generateContent")
        self.assertEqual(
            op["requestBody"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/GeminiGenerateContentRequest"},
        )
        request = self.schemas["GeminiGenerateContentRequest"]
        self.assertEqual(request["required"], ["contents"])
        self.assertLessEqual(
            {
                "contents",
                "systemInstruction",
                "tools",
                "toolConfig",
                "generationConfig",
                "safetySettings",
            },
            set(request["properties"]),
        )
        part = self.schemas["GeminiPart"]["properties"]
        self.assertLessEqual(
            {"text", "inlineData", "functionCall", "functionResponse", "thought"},
            set(part),
        )
        self.assertIn("googleSearch", self.schemas["GeminiTool"]["properties"])
        declaration = self.schemas["GeminiFunctionDeclaration"]["properties"]
        self.assertLessEqual({"parameters", "parametersJsonSchema"}, set(declaration))
        function_config = self.schemas["GeminiFunctionCallingConfig"]["properties"]
        self.assertEqual(function_config["mode"]["enum"], ["AUTO", "ANY", "NONE"])
        self.assertIn("allowedFunctionNames", function_config)
        generation = self.schemas["GeminiGenerationConfig"]["properties"]
        self.assertLessEqual(
            {
                "temperature",
                "topP",
                "topK",
                "maxOutputTokens",
                "stopSequences",
                "seed",
                "responseMimeType",
                "responseSchema",
                "responseJsonSchema",
                "thinkingConfig",
            },
            set(generation),
        )

    def test_unsupported_candidates_and_ignored_safety_name_the_fields(self) -> None:
        config = self.schemas["GeminiGenerationConfig"]["properties"]
        self.assertEqual(config["candidateCount"]["maximum"], 1)
        description = self.operation("/{model}:generateContent")["description"]
        self.assertIn("candidateCount", description)
        self.assertIn("safetySettings", description)
        self.assertIn("x-eugene-plexus-ignored-settings", description)
        self.assertIn("observed cause", description)

    def test_response_reports_actual_model_usage_and_thoughts(self) -> None:
        response = self.schemas["GeminiGenerateContentResponse"]
        self.assertLessEqual(
            {"candidates", "usageMetadata", "modelVersion"}, set(response["required"])
        )
        self.assertIn(
            "actually answered", response["properties"]["modelVersion"]["description"]
        )
        candidate = self.schemas["GeminiCandidate"]["properties"]
        self.assertEqual(
            candidate["finishReason"]["enum"], ["STOP", "MAX_TOKENS", "SAFETY"]
        )
        usage = self.schemas["GeminiUsageMetadata"]["properties"]
        self.assertLessEqual(
            {
                "promptTokenCount",
                "candidatesTokenCount",
                "totalTokenCount",
                "thoughtsTokenCount",
                "cachedContentTokenCount",
            },
            set(usage),
        )
        thoughts = self.schemas["GeminiThinkingConfig"]["properties"]
        self.assertLessEqual(
            {"thinkingLevel", "thinkingBudget", "includeThoughts"}, set(thoughts)
        )

    def test_stream_is_sse_of_gemini_responses(self) -> None:
        op = self.operation("/{model}:streamGenerateContent")
        alt = next(p for p in op["parameters"] if p["name"] == "alt")
        self.assertEqual(alt["in"], "query")
        self.assertEqual(alt["schema"]["enum"], ["sse"])
        self.assertEqual(
            op["responses"]["200"]["content"]["text/event-stream"]["schema"],
            {"$ref": "#/components/schemas/GeminiStreamGenerateContentResponse"},
        )
        self.assertNotIn(
            "required", self.schemas["GeminiStreamGenerateContentResponse"]
        )
        self.assertIn("[DONE]", op["description"])
        self.assertIn("x-eugene-plexus-", op["description"])

    def test_sdk_dictionary_spellings_are_carried_as_measured(self) -> None:
        declaration = self.schemas["GeminiFunctionDeclaration"]["properties"]
        self.assertIn("parameters_json_schema", declaration)
        thinking = self.schemas["GeminiThinkingConfig"]["properties"]
        self.assertLessEqual(
            {"include_thoughts", "thinking_level", "thinking_budget"}, set(thinking)
        )

    def test_errors_use_google_envelope_and_name_observed_causes(self) -> None:
        op = self.operation("/{model}:generateContent")
        for status in ("400", "401", "403", "404", "429", "502", "503", "504"):
            schema = op["responses"][status]["content"]["application/json"]["schema"]
            self.assertEqual(
                schema, {"$ref": "#/components/schemas/GeminiErrorResponse"}
            )
        error = self.schemas["GeminiErrorResponse"]["properties"]["error"]
        self.assertEqual(set(error["required"]), {"code", "message", "status"})
        self.assertIn("observed cause", error["properties"]["message"]["description"])

    def test_count_tokens_has_native_request_and_response(self) -> None:
        op = self.operation("/{model}:countTokens")
        self.assertEqual(
            op["requestBody"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/GeminiCountTokensRequest"},
        )
        request = self.schemas["GeminiCountTokensRequest"]["properties"]
        self.assertLessEqual({"contents", "generateContentRequest"}, set(request))
        self.assertEqual(
            op["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/GeminiCountTokensResponse"},
        )
        self.assertIn(
            "totalTokens", self.schemas["GeminiCountTokensResponse"]["required"]
        )
        self.assertIn("Nothing is generated", op["description"])

    def test_model_names_default_to_chat_and_have_effective_gui_overrides(self) -> None:
        config = self.gateway["paths"]["/v1/config"]
        description = " ".join(config["get"]["description"].split())
        for text in (
            "geminiModelNames",
            "Gemini model names",
            "role:chat",
            "model_slots",
            "effective",
            "GUI",
            "never block",
        ):
            self.assertIn(text, description)
        self.assertIn("geminiModelNames", config["patch"]["description"])
        mapping = self.schemas["GeminiModelNameMapping"]
        self.assertEqual(set(mapping["required"]), {"model", "targets"})
        self.assertEqual(mapping["properties"]["targets"]["maxItems"], 1)

    def test_model_metadata_supports_pagination_and_truthful_capabilities(self) -> None:
        op = self.operation("", "get")
        self.assertEqual(
            {p["name"] for p in op["parameters"]}, {"pageSize", "pageToken"}
        )
        self.assertLessEqual(
            {"models", "nextPageToken"},
            set(self.schemas["GeminiListModelsResponse"]["properties"]),
        )
        model = self.schemas["GeminiModel"]["properties"]
        self.assertLessEqual(
            {
                "name",
                "displayName",
                "inputTokenLimit",
                "outputTokenLimit",
                "supportedGenerationMethods",
            },
            set(model),
        )
        self.assertIn("unknown", model["inputTokenLimit"]["description"])

    def test_v1_model_reads_preserve_openai_and_add_gemini_projection(self) -> None:
        listing = self.schemas["ModelList"]
        self.assertLessEqual({"object", "data", "models"}, set(listing["required"]))
        self.assertEqual(
            listing["properties"]["models"]["items"],
            {"$ref": "#/components/schemas/GeminiModel"},
        )
        model = self.schemas["Model"]
        self.assertIn("id", model["required"])
        self.assertIn("name", model["required"])
        self.assertIn("supportedGenerationMethods", model["properties"])
        for path in ("/v1/models", "/v1/models/{model}"):
            description = self.gateway["paths"][path]["get"]["description"]
            self.assertIn("Gemini", description)
            self.assertIn("x-goog-api-key", description)

    def test_driver_dimensions_are_optional_positive_and_not_emulated(self) -> None:
        request = self.driver["components"]["schemas"]["EmbedRequest"]
        dimensions = request["properties"]["dimensions"]
        self.assertEqual(dimensions["type"], "integer")
        self.assertEqual(dimensions["minimum"], 1)
        self.assertNotIn("dimensions", request["required"])
        self.assertNotIn("default", dimensions)
        self.assertIn("outputDimensionality", dimensions["description"])
        self.assertIn("never truncates", dimensions["description"])

    def test_embeddings_only_call_dimensions_ignored_when_not_applied(self) -> None:
        description = " ".join(
            self.gateway["paths"]["/v1/embeddings"]["post"]["description"].split()
        )
        self.assertIn("outputDimensionality", description)
        self.assertIn("only when", description)
        self.assertIn("x-eugene-plexus-ignored-settings", description)
        dimensions = self.schemas["EmbeddingRequest"]["properties"]["dimensions"]
        self.assertNotIn("Accepted and ignored", dimensions["description"])

    def test_existing_count_contracts_include_gemini_and_multimodal_counts(
        self,
    ) -> None:
        for document, path in (
            (self.driver, "/v1/generate/count"),
            (self.gateway, "/v1/messages/count_tokens"),
            (self.gateway, "/v1/responses/input_tokens"),
        ):
            description = document["paths"][path]["post"]["description"]
            self.assertIn("Gemini", description)
            self.assertIn("countTokens", description)
        driver_count = self.driver["paths"]["/v1/generate/count"]["post"]["description"]
        self.assertNotIn("Every other backend", driver_count)
        self.assertNotIn("A request carrying an image is 501 too", driver_count)

    def test_gemini_speech_names_conversion_formats_and_encoder_failures(self) -> None:
        description = self.driver["paths"]["/v1/speak"]["post"]["description"]
        for text in ("Gemini", "PyAV", "mp3", "opus", "observed cause"):
            self.assertIn(text, description)


if __name__ == "__main__":
    unittest.main()
