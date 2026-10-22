"""Offline contract checks for row 29: pictures returned by tools."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

OPENAPI = Path(__file__).resolve().parents[1] / "openapi"


def description(node: dict) -> str:
    return " ".join(node["description"].split())


class ToolPicturesContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.documents = {
            name: yaml.safe_load((OPENAPI / name).read_text(encoding="utf-8"))
            for name in (
                "components/common.yaml",
                "gateway.yaml",
                "inference-driver.yaml",
                "site-host.yaml",
                "control.yaml",
            )
        }
        cls.common = cls.documents["components/common.yaml"]["components"]["schemas"]

    def test_shared_content_allows_tool_images_but_keeps_audio_and_files_on_users(
        self,
    ) -> None:
        content = description(self.common["MessageContent"])
        self.assertIn("Images ride on user messages and on tool results", content)
        self.assertIn("Audio and files ride on user messages only", content)
        for limit in (
            "12 by default",
            "at most 64",
            "5 MiB decoded each",
            "10 MiB decoded total",
            "11 MiB decoded",
        ):
            with self.subTest(limit=limit):
                self.assertIn(limit, content)

    def test_chat_tool_content_accepts_text_and_image_parts(self) -> None:
        message = self.documents["gateway.yaml"]["components"]["schemas"][
            "ChatCompletionMessage"
        ]["properties"]
        content = message["content"]
        self.assertEqual(
            content["$ref"],
            "./components/common.yaml#/components/schemas/MessageContent",
        )
        self.assertIn(
            "the result, as a string or an array of text and image parts",
            description(content),
        )
        self.assertIn("next user message", description(content))
        self.assertIn("call id", description(content))
        self.assertNotIn("result, as a string —", description(message["tool_call_id"]))

    def test_all_three_doors_use_the_shared_tool_image_path(self) -> None:
        gateway = self.documents["gateway.yaml"]
        for path in ("/v1/chat/completions", "/v1/messages", "/v1/responses"):
            with self.subTest(path=path):
                operation = description(gateway["paths"][path]["post"])
                self.assertIn("MessageContent", operation)
                self.assertIn("next user message", operation)
                self.assertIn("newest tool pictures", operation)
                self.assertIn("confirms image input", operation)
        chat = description(gateway["paths"]["/v1/chat/completions"]["post"])
        self.assertIn("`image_url`", chat)
        self.assertIn("GIF and WebP", chat)
        self.assertIn("re-encoded to PNG", chat)

    def test_newest_tool_pictures_fit_the_limits_and_omissions_name_the_cause(
        self,
    ) -> None:
        content = description(self.common["MessageContent"])
        self.assertIn("Tool pictures count toward these same limits", content)
        self.assertIn("image count or decoded-byte limits", content)
        self.assertIn("keeps the newest tool pictures that fit", content)
        self.assertIn("note in its tool message naming the limit", content)
        self.assertIn(
            "[A picture this tool returned is not attached: "
            "this request holds at most 12 pictures.]",
            content,
        )

    def test_a_persons_own_pictures_are_never_dropped(self) -> None:
        content = description(self.common["MessageContent"])
        self.assertIn("A person's own pictures are never dropped", content)
        self.assertIn("if they alone exceed a limit, the request is a 400", content)

    def test_driver_tool_messages_keep_text_and_images_move_to_user_messages(
        self,
    ) -> None:
        messages = self.documents["inference-driver.yaml"]["components"]["schemas"][
            "GenerateRequest"
        ]["properties"]["messages"]
        self.assertEqual(
            messages["items"],
            {"$ref": "components/common.yaml#/components/schemas/Message"},
        )
        self.assertIn("Tool messages carry text", description(messages))
        self.assertIn("next user message", description(messages))
        self.assertIn("Message.toolCallId", description(messages))
        call = description(self.common["Message"]["properties"]["toolCallId"])
        self.assertIn("inference-driver", call)
        self.assertIn("next user message", call)

    def test_site_tool_answers_allow_8_mib_and_other_answers_keep_70000_bytes(
        self,
    ) -> None:
        site = description(self.documents["site-host.yaml"]["info"])
        self.assertIn("8 MiB (8,388,608 bytes)", site)
        self.assertIn("`tools/call`", site)
        self.assertIn("other answers keep the 70,000-byte limit", site)
        self.assertIn("The answer is larger than 8 MiB. Ask for less.", site)

    def test_control_result_is_bounded_to_8_mib_and_never_logged(self) -> None:
        operation = self.documents["control.yaml"]["paths"][
            "/v1/sites/operations/{ident}/result"
        ]["post"]
        result = description(operation)
        self.assertIn("8 MiB (8,388,608 bytes)", result)
        self.assertIn("held in memory", result)
        self.assertIn("never in the log", result)
        self.assertIn("access is checked once more", result)
        self.assertEqual(
            operation["responses"]["413"]["description"],
            "The answer is larger than 8 MiB. Ask for less.",
        )

    def test_control_mcp_call_documents_method_specific_answer_caps(self) -> None:
        operation = description(
            self.documents["control.yaml"]["paths"]["/oidc/sites/mcp"]["post"]
        )
        self.assertIn("40,000 bytes", operation)
        self.assertIn("8 MiB for `tools/call`", operation)
        self.assertIn("70,000 bytes for other answers", operation)


if __name__ == "__main__":
    unittest.main()
