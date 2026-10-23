"""Offline checks of the Linux acceptance's evidence checks, never its install."""

import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).with_name("mv5b-hindsight-acceptance.py")


class EvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        spec = importlib.util.spec_from_file_location("hindsight_acceptance", PATH)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_network_evidence_requires_loopback_and_rejects_ipv6_and_public_binds(self) -> None:
        check = self.module.check_network
        self.assertGreater(check('connect(3, {sa_family=AF_INET, sin_addr=inet_addr("127.0.0.1")}, 16) = 0'), 0)
        for text in (
            'connect(3, {sa_family=AF_INET, sin_addr=inet_addr("8.8.8.8")}, 16) = 0',
            'bind(3, {sa_family=AF_INET, sin_addr=inet_addr("0.0.0.0")}, 16) = 0',
            'connect(3, {sa_family=AF_INET6, inet_pton(AF_INET6, "2001:4860::8888", &sin6_addr)}, 28) = -1',
            '',
        ):
            with self.subTest(text=text), self.assertRaises(AssertionError):
                check(text)

    def test_stub_extracts_distinct_content_from_each_person(self) -> None:
        first = self.module.extraction({"messages": [{"content": "MV5B_ADA"}]})
        second = self.module.extraction({"messages": [{"content": "MV5B_BOB"}]})
        self.assertIn("MV5B_ADA", first)
        self.assertNotIn("MV5B_BOB", first)
        self.assertIn("MV5B_BOB", second)


if __name__ == "__main__":
    unittest.main()
