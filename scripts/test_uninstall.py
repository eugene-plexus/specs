"""Removal tests use temporary installs; no real service or credential store."""

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "inventory", ROOT / "uninstall_inventory.py"
)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


class RemovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eugene removal '")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.prefix = self.root / "Eugene"
        self.prefix.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = patch.dict(
            os.environ,
            {
                "HOME": str(self.home),
                "USERPROFILE": str(self.home),
                "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(self.prefix / "engines"),
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.write("agent.yaml", "{}")

    def write(self, name, content="data"):
        path = self.prefix / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_inventory_separates_software_data_downloads_and_originals(self):
        self.write("venv/package/file")
        self.write("apps/chat/versions/1/venv/bin/python")
        self.write("apps/chat/data/chat.sqlite3")
        self.write("control-state/keys.json")
        self.write("library-state.runs.sqlite3-wal")
        self.write("gateway.yaml.unreadable")
        self.write("models/original.gguf")
        self.write("engines/llama/server")
        plan = inventory.inventory(self.prefix)
        self.assertIn(str(self.prefix / "venv"), plan["software"])
        self.assertIn(str(self.prefix / "apps/chat/versions"), plan["software"])
        self.assertIn(str(self.prefix / "apps/chat/data"), plan["data"])
        self.assertIn(str(self.prefix / "control-state"), plan["data"])
        self.assertIn(str(self.prefix / "library-state.runs.sqlite3-wal"), plan["data"])
        self.assertIn(str(self.prefix / "gateway.yaml.unreadable"), plan["data"])
        self.assertIn(str(self.prefix / "engines"), plan["downloads"])
        for kind in ("software", "data", "downloads"):
            self.assertNotIn(str(self.prefix / "models"), plan[kind])

    def test_model_copy_directory_cannot_delete_an_original_library_folder(self):
        models = self.root / "original models"
        models.mkdir()
        self.write("agent.yaml", "modelCopyDir: " + json.dumps(str(models)))
        self.write(
            "library.yaml",
            "modelRoots:\n  - path: " + json.dumps(str(models)) + "\n    mounts: []\n",
        )
        plan = inventory.inventory(self.prefix)
        self.assertNotIn(str(models), plan["downloads"])
        self.assertTrue(any("original model folder" in w for w in plan["warnings"]))

    def test_dangerous_copy_path_is_kept(self):
        self.write("agent.yaml", "modelCopyDir: " + json.dumps(str(self.home)))
        self.assertEqual([], inventory.inventory(self.prefix)["downloads"])

    def test_broken_yaml_is_reported(self):
        self.write("agent.yaml", "[bad")
        self.write("engines/keep-on-error")
        self.assertTrue(inventory.inventory(self.prefix)["warnings"])
        self.assertEqual([], inventory.inventory(self.prefix)["downloads"])

    def test_relative_copy_location_is_not_resolved_against_the_removers_directory(
        self,
    ):
        self.write("agent.yaml", "modelCopyDir: ../other-persons-models")
        result = inventory.inventory(self.prefix)
        self.assertEqual([], result["downloads"])
        self.assertTrue(any("working directory" in w for w in result["warnings"]))

    @unittest.skipUnless(
        sys.platform == "darwin", "AppleScript compiler is available on Mac CI"
    )
    def test_mac_dialog_scripts_compile_without_opening_dialogs(self):
        bodies = re.findall(
            r"<<'APPLE'[^\n]*\n(.*?)\nAPPLE",
            (ROOT / "uninstall.sh").read_text(),
            re.DOTALL,
        )
        self.assertGreaterEqual(len(bodies), 4)
        for i, body in enumerate(bodies):
            source = self.root / f"dialog-{i}.applescript"
            source.write_text(body, encoding="utf-8")
            result = subprocess.run(
                [
                    "/usr/bin/osacompile",
                    "-o",
                    str(self.root / f"dialog-{i}.scpt"),
                    str(source),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)

    def test_credentials_use_the_actual_application_names_and_report_failures(self):
        salt = base64.b64encode(b"test salt not a secret").decode()
        fingerprint = hashlib.sha256(b"test salt not a secret").hexdigest()[:12]
        username = "master-key:" + fingerprint
        self.write("agent.yaml", f"auth:\n  masterSalt: {salt}\n")

        class Vault:
            entries = {
                ("eugene-plexus-agent", username): "test",
                ("eugene-plexus-control", username): "test",
                ("other", username): "keep",
            }

            def get_password(self, service, user):
                return self.entries.get((service, user))

            def delete_password(self, service, user):
                if service == "eugene-plexus-control":
                    raise RuntimeError("vault locked")
                del self.entries[service, user]

        vault = Vault()
        with patch.dict(sys.modules, {"keyring": vault}):
            result = inventory.keyring_cleanup(self.prefix)
        self.assertEqual(1, result["removed"])
        self.assertTrue(any("vault locked" in w for w in result["warnings"]))
        self.assertIn(("other", username), vault.entries)

    def test_mac_bundle_launches_the_local_utility_with_quoted_paths(self):
        (self.prefix / "uninstall").mkdir()
        inventory.install_macos(self.prefix)
        apps = list((self.home / "Applications").glob("Remove Eugene*.app"))
        self.assertEqual(1, len(apps))
        body = (apps[0] / "Contents/MacOS/remove").read_text()
        import shlex

        self.assertIn(shlex.quote(str(self.prefix / "uninstall/remove.sh")), body)
        self.assertNotIn("curl", body)

    @unittest.skipIf(
        os.name == "nt", "POSIX executable integration runs under WSL and CI"
    )
    def test_offline_two_pass_removal_without_recreating_config_or_python(self):
        self.write("models/original.gguf")
        self.write("engines/llama/server")
        self.write("apps/chat/versions/1/venv/package")
        self.write("apps/chat/data/chat.sqlite3")
        self.write("logs/log.txt")
        copies = self.root / "managed copies"
        copies.mkdir()
        (copies / "model.gguf").write_text("copy")
        self.write("agent.yaml", "modelCopyDir: " + json.dumps(str(copies)))
        self.write("venv/bin/placeholder")
        (self.prefix / "venv/bin/python").symlink_to(sys.executable)
        self.write("uninstall/placeholder")
        shutil.copyfile(
            ROOT / "uninstall_inventory.py", self.prefix / "uninstall/inventory.py"
        )
        shutil.copyfile(ROOT / "uninstall.sh", self.prefix / "uninstall/remove.sh")
        command = [
            "/bin/sh",
            str(self.prefix / "uninstall/remove.sh"),
            "--prefix",
            str(self.prefix),
        ]
        first = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        kept = next(self.root.glob("Eugene.removed-*"))
        self.assertFalse((kept / "venv").exists())
        self.assertFalse((kept / "apps/chat/versions").exists())
        self.assertTrue((kept / "agent.yaml").exists())
        self.assertTrue((kept / "apps/chat/data/chat.sqlite3").exists())
        self.assertTrue((kept / "models/original.gguf").exists())
        self.assertTrue(copies.exists())
        second = subprocess.run(
            [
                "/bin/sh",
                str(kept / "uninstall/remove.sh"),
                "--purge-downloads",
                "--purge-data",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        self.assertFalse((kept / "agent.yaml").exists())
        self.assertFalse((kept / "apps/chat/data").exists())
        self.assertFalse((kept / "engines").exists())
        self.assertFalse(copies.exists())
        self.assertTrue((kept / "models/original.gguf").exists())
        self.assertEqual("data", (kept / "models/original.gguf").read_text())
        third = subprocess.run(
            [
                "/bin/sh",
                str(kept / "uninstall/remove.sh"),
                "--purge-downloads",
                "--purge-data",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, third.returncode, third.stdout + third.stderr)


if __name__ == "__main__":
    unittest.main()
