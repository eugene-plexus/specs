"""Offline row 57 contract checks. Run directly or through pytest."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

CONTRACT = Path(__file__).resolve().parents[1] / "openapi" / "gateway.yaml"
CLIENT_TOOLS = ("custom", "local_shell", "shell", "apply_patch")


def description(schema: dict) -> str:
    return " ".join(schema["description"].split())


class ResponsesToolsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        cls.schemas = cls.contract["components"]["schemas"]
        cls.create = cls.contract["paths"]["/v1/responses"]["post"]

    def resolve(self, schema: dict) -> dict:
        if "$ref" in schema:
            return self.schemas[schema["$ref"].rsplit("/", 1)[-1]]
        return schema

    def test_client_run_tools_are_translated_without_gateway_execution(self) -> None:
        tool = self.schemas["ResponsesTool"]
        text = description(tool)
        for name in CLIENT_TOOLS:
            with self.subTest(tool=name):
                self.assertIn(f"`{name}`", text)
        self.assertIn("client executes", text)
        self.assertIn("function", text)
        self.assertTrue(tool["additionalProperties"])
        self.assertNotIn("enum", tool["properties"]["type"])

    def test_custom_grammar_is_described_and_named_as_ignored(self) -> None:
        tool_format = self.schemas["ResponsesTool"]["properties"]["format"]
        self.assertEqual(tool_format["type"], "object")
        self.assertEqual(tool_format["properties"]["type"]["enum"], ["text", "grammar"])
        for phrase in (
            "Lark",
            "regex",
            "not enforced",
            "function description",
            "tools[i].format",
            "x-eugene-plexus-ignored-settings",
        ):
            self.assertIn(phrase, description(tool_format))

    def test_tool_choice_can_force_a_client_run_tool(self) -> None:
        choice = self.schemas["ResponsesRequest"]["properties"]["tool_choice"]
        for name in CLIENT_TOOLS:
            with self.subTest(tool=name):
                self.assertIn(f"`{name}`", description(choice))
        self.assertNotIn("Forcing any other tool type is refused", description(choice))
        self.assertNotIn("not a function", description(self.create))

    def test_client_call_items_can_be_returned_and_replayed(self) -> None:
        incoming = self.schemas["ResponsesInputItem"]
        outgoing = self.schemas["ResponsesOutputItem"]
        for name in CLIENT_TOOLS:
            call = f"{name}_tool_call" if name == "custom" else f"{name}_call"
            with self.subTest(call=call):
                self.assertIn(call, outgoing["properties"]["type"]["enum"])
                self.assertIn(f"`{call}`", description(incoming))
                self.assertIn(f"`{call}_output`", description(incoming))
        for item in (incoming, outgoing):
            properties = item["properties"]
            self.assertEqual(properties["call_id"]["type"], "string")
            self.assertEqual(properties["input"]["type"], "string")
            self.assertEqual(self.resolve(properties["action"])["type"], "object")
            self.assertEqual(self.resolve(properties["operation"])["type"], "object")
        self.assertIn("call_id", description(incoming))
        self.assertIn("stdout", description(incoming["properties"]["output"]))
        self.assertIn("failed", description(incoming["properties"]["status"]))

    def test_shell_and_patch_shapes_use_openai_fields(self) -> None:
        properties = self.schemas["ResponsesOutputItem"]["properties"]
        action = self.resolve(properties["action"])["properties"]
        for name in ("command", "commands"):
            self.assertEqual(action[name]["type"], "array")
            self.assertEqual(action[name]["items"]["type"], "string")
        self.assertEqual(action["working_directory"]["type"], "string")
        self.assertEqual(action["env"]["additionalProperties"], {"type": "string"})
        for name in ("timeout_ms", "max_output_length"):
            self.assertIn("integer", action[name]["type"])
        operation = self.resolve(properties["operation"])["properties"]
        self.assertEqual(
            operation["type"]["enum"], ["create_file", "delete_file", "update_file"]
        )
        self.assertEqual(operation["path"]["type"], "string")
        self.assertEqual(operation["diff"]["type"], "string")

    def test_stream_uses_custom_input_and_shell_command_events(self) -> None:
        event = self.schemas["ResponsesStreamEvent"]
        kinds = event["properties"]["type"]["enum"]
        for kind in (
            "response.custom_tool_call_input.delta",
            "response.custom_tool_call_input.done",
            "response.shell_call_command.added",
            "response.shell_call_command.delta",
            "response.shell_call_command.done",
        ):
            self.assertIn(kind, kinds)
        for name in ("item_id", "delta", "input", "command"):
            self.assertEqual(event["properties"][name]["type"], "string")
        for name in ("output_index", "command_index"):
            self.assertEqual(event["properties"][name]["type"], "integer")
        self.assertEqual(
            event["properties"]["item"]["$ref"],
            "#/components/schemas/ResponsesOutputItem",
        )
        self.assertIn("local_shell_call", description(event))
        self.assertIn("apply_patch_call", description(event))
        self.assertIn("response.output_item.done", description(event))

    def test_refused_tools_name_the_reason_and_alternative(self) -> None:
        text = description(self.create)
        for cause in (
            "computer_use_preview",
            "no local model is trained",
            "code_interpreter",
            "no sandbox",
            "use a function tool and run it yourself",
            "file_search",
            "row 56",
        ):
            self.assertIn(cause, text)
        # Row 59b: remote MCP runs; it is no longer among the refused.
        refused = text[text.index("Tools still refused") :].split("\n\n", 1)[0]
        self.assertNotIn("`mcp`", refused)
        self.assertIn("`mcp` (remote MCP, row 59b) runs on a tool-driver", " ".join(text.split()))

    def test_remote_mcp_items_and_events_are_named(self) -> None:
        kinds = self.schemas["ResponsesOutputItem"]["properties"]["type"]["enum"]
        for kind in ("mcp_list_tools", "mcp_call", "mcp_approval_request"):
            self.assertIn(kind, kinds)
        events = self.schemas["ResponsesStreamEvent"]["properties"]["type"]["enum"]
        for event in (
            "response.mcp_list_tools.in_progress",
            "response.mcp_list_tools.completed",
            "response.mcp_call.in_progress",
            "response.mcp_call_arguments.done",
            "response.mcp_call.completed",
            "response.mcp_call.failed",
        ):
            self.assertIn(event, events)
        tool = self.schemas["ResponsesTool"]["properties"]
        for name in ("server_label", "server_url", "headers", "authorization", "require_approval"):
            self.assertIn(name, tool)

    def test_compact_has_its_own_request_and_response(self) -> None:
        operation = self.contract["paths"]["/v1/responses/compact"]["post"]
        self.assertEqual(operation["operationId"], "compactResponse")
        self.assertEqual(
            operation["requestBody"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/ResponsesCompactRequest"},
        )
        self.assertEqual(
            operation["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/ResponsesCompactResponse"},
        )
        for status in ("400", "401", "502", "503", "504"):
            self.assertEqual(
                operation["responses"][status]["content"]["application/json"]["schema"],
                {"$ref": "#/components/schemas/OpenAIErrorResponse"},
            )
        request = self.schemas["ResponsesCompactRequest"]
        self.assertEqual(set(request["required"]), {"model", "input"})
        self.assertEqual(request["properties"]["model"]["type"], "string")
        self.assertEqual(
            request["properties"]["input"],
            self.schemas["ResponsesRequest"]["properties"]["input"],
        )
        self.assertIn(
            "row 54", description(request["properties"]["previous_response_id"])
        )
        self.assertNotIn("stream", request["properties"])
        response = self.schemas["ResponsesCompactResponse"]
        self.assertEqual(
            set(response["required"]), {"id", "object", "created_at", "output", "usage"}
        )
        self.assertEqual(
            response["properties"]["object"]["const"], "response.compaction"
        )
        self.assertEqual(response["properties"]["output"]["minItems"], 1)
        self.assertEqual(
            response["properties"]["output"]["items"]["$ref"],
            "#/components/schemas/ResponsesOutputItem",
        )
        self.assertEqual(
            response["properties"]["usage"]["$ref"],
            "#/components/schemas/ResponsesUsage",
        )

    def test_compaction_is_opaque_authenticated_and_replayed_as_developer(self) -> None:
        operation = self.contract["paths"]["/v1/responses/compact"]["post"]
        text = description(operation)
        for phrase in (
            "4,000",
            "fixed",
            "asked",
            "decided",
            "done",
            "open threads",
            "files touched",
            "encrypted and authenticated",
            "gateway",
            "key",
            "restart",
            "no response store",
        ):
            self.assertIn(phrase, text)
        self.assertIn(
            "ending with", description(self.schemas["ResponsesCompactResponse"])
        )
        incoming = self.schemas["ResponsesInputItem"]
        outgoing = self.schemas["ResponsesOutputItem"]
        self.assertIn("compaction", outgoing["properties"]["type"]["enum"])
        self.assertEqual(outgoing["properties"]["encrypted_content"]["type"], "string")
        self.assertIn("developer message", description(incoming))
        self.assertIn(
            "authenticated", description(incoming["properties"]["encrypted_content"])
        )
        self.assertIn(
            "This compaction was made elsewhere; send the conversation instead.",
            description(operation["responses"]["400"]),
        )


if __name__ == "__main__":
    unittest.main()
