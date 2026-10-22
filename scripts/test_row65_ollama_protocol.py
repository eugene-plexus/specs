"""Keep acceptance must retain the production proxy and realistic credentials."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


class OllamaProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        source = Path(__file__).with_name("row65-ollama-protocol.py")
        self.tree = ast.parse(source.read_text(encoding="utf-8"))

    def test_protocol_mounts_real_proxy(self) -> None:
        aliases = {
            alias.asname or alias.name
            for node in ast.walk(self.tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "eugene_plexus_agent.routes.proxy"
            for alias in node.names
            if alias.name == "router"
        }
        mounted = {
            node.args[0].id
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "include_router"
            and node.args
            and isinstance(node.args[0], ast.Name)
        }
        self.assertTrue(aliases & mounted, "Acceptance must mount the real proxy")
        for node in ast.walk(self.tree):
            if isinstance(node, ast.keyword) and node.arg == "prefix":
                self.assertNotIn("/api/proxy", ast.unparse(node.value))

    def test_protocol_uses_single_audience_exchanged_session(self) -> None:
        sessions = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            typ = keywords.get("typ")
            if isinstance(typ, ast.Attribute) and typ.attr == "TYP_SESSION":
                sessions.append(keywords)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(ast.literal_eval(sessions[0]["aud"]), ["node:library"])
        self.assertEqual(
            ast.literal_eval(sessions[0]["extra"])["act"], {"sub": "node:console"}
        )


if __name__ == "__main__":
    unittest.main()
