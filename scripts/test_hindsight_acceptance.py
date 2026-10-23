"""Offline checks of the Linux acceptance's evidence checks, never its install."""

import importlib.util
import unittest
from unittest.mock import patch
from types import SimpleNamespace
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

    def test_login_checks_require_authentication_refusal_and_test_both_transports(self) -> None:
        calls = []
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            password = kwargs["env"].get("PGPASSWORD")
            return SimpleNamespace(returncode=0 if password == "generated" else 2,
                stdout="1\n" if password == "generated" else "",
                stderr="password authentication failed" if password else "no password supplied")
        with patch.object(self.module.subprocess, "run", run):
            result = self.module.check_database_logins(8499, 123, "generated", "runner")
        self.assertEqual(len(result), 6)
        self.assertEqual(len(calls), 6)
        self.assertEqual(sum("nsenter" in argv for argv, _ in calls), 3)
        self.assertEqual(sum("127.0.0.1" in argv for argv, _ in calls), 3)
        self.assertTrue(all("-w" in argv for argv, _ in calls))
        with patch.object(self.module.subprocess, "run", return_value=SimpleNamespace(
            returncode=2, stdout="", stderr="Connection refused")):
            with self.assertRaisesRegex(AssertionError, "authentication"):
                self.module.check_database_logins(8499, 123, "generated", "runner")

    def test_systemd_setup_reuses_installer_units_and_cannot_touch_a_developer_install(self) -> None:
        with patch.dict(self.module.os.environ, {"GITHUB_ACTIONS": "false"}):
            with self.assertRaisesRegex(AssertionError, "CI"):
                self.module.prepare_systemd(Path(".codex-tmp/ci"))
        script = self.module.systemd_setup_script(Path("/var/lib/test/.codex-tmp/ci"), "runner")
        self.assertIn("write_app_units()", script)
        self.assertIn("DynamicUser=yes", script)
        self.assertIn("LoadCredential=memory_server_token:", script)
        self.assertIn("ProtectHome=yes", script)
        self.assertIn("StateDirectory=eugene-plexus-mv5b/.codex-tmp/%i", script)

    def test_acceptance_uses_systemd_and_password_checks(self) -> None:
        text = PATH.read_text()
        self.assertIn('AccountSupport("systemd")', text)
        self.assertIn('check_database_logins(', text)
        self.assertIn('pg0-embedded', text)
        self.assertIn('eugene-plexus-hindsight', text)


if __name__ == "__main__":
    unittest.main()
