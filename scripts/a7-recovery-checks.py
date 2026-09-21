"""Adversarial checkpoint tests; disposable state only, no installed service."""

import base64
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
import tempfile
from unittest.mock import patch

import yaml
from eugene_plexus_agent import security

spec = importlib.util.spec_from_file_location(
    "recovery", Path(__file__).with_name("recovery.py")
)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


def refused(action, label):
    try:
        action()
    except Exception:
        print("PASS refusal:", label)
    else:
        raise AssertionError("did not refuse " + label)


def run():
    with tempfile.TemporaryDirectory(prefix="ep-a7-checks-") as temporary:
        root = Path(temporary) / "source"
        root.mkdir()
        phrase = "isolated-checkpoint-unlock"
        salt = security.generate_master_key_salt()
        key = security.derive_master_key(phrase, salt)
        (root / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "auth": {
                        "passphraseHash": security.hash_passphrase(phrase),
                        "masterSalt": base64.b64encode(salt).decode(),
                    },
                    "components": [],
                    "runtimes": [],
                    "securityMode": "prompt_on_startup",
                }
            ),
            encoding="utf-8",
        )
        (root / "driver.yaml").write_text(
            yaml.safe_dump({"apiKey": security.seal("provider-secret", key).to_dict()}),
            encoding="utf-8",
        )
        (root / "client_keys.json").write_text(
            '{"revoked-key":{"revoked":true,"localOnly":true}}'
        )
        with closing(sqlite3.connect(root / "metrics.sqlite3")) as db:
            db.execute("CREATE TABLE events (id INTEGER)")
            db.execute("INSERT INTO events VALUES (7)")
            db.commit()
        (root / "logs").mkdir()
        (root / "logs" / "discard.log").write_text("not retained")
        model = root / "model.gguf"
        model.write_bytes(b"external-model")
        baseline = {
            str(p.relative_to(root)): recovery.digest(p)
            for p in root.rglob("*")
            if p.is_file()
        }
        environment = {
            "os": sys.platform,
            "arch": platform.machine(),
            "python": platform.python_version(),
            "packages": [],
        }
        destination = Path(temporary) / "backup"
        with patch.object(recovery, "environment", return_value=environment):
            refused(
                lambda: recovery.backup(
                    root, destination, "password", {}, [], stopped=True
                ),
                "missing unlock material",
            )
            refused(
                lambda: recovery.backup(
                    root, destination, "password", {"agent": "wrong"}, [], stopped=True
                ),
                "wrong unlock material",
            )
            assert not destination.exists()
            refused(
                lambda: recovery.backup(
                    root, destination, "password", {"agent": phrase}, [], stopped=False
                ),
                "no stopped acknowledgement",
            )
            recovery.backup(
                root, destination, "password", {"agent": phrase}, [], stopped=True
            )
        assert not any(
            b"provider-secret" in p.read_bytes() or phrase.encode() in p.read_bytes()
            for p in destination.iterdir()
        )
        manifest, box = recovery.read_checkpoint(destination, "password")
        assert "logs" in manifest["excluded"]
        assert manifest["externalAssets"][0]["sha256"] == recovery.digest(model)
        replacement = Path(temporary) / "replacement"
        refused(
            lambda: recovery.restore(
                destination, replacement, "wrong", None, reconstruct=False
            ),
            "wrong backup password",
        )
        assert not replacement.exists()
        original_manifest = (destination / "manifest.sealed").read_bytes()
        manifest["format"] = 999
        (destination / "manifest.sealed").write_bytes(
            box.encrypt(json.dumps(manifest).encode())
        )
        refused(
            lambda: recovery.restore(
                destination, replacement, "password", None, reconstruct=False
            ),
            "future backup format",
        )
        assert not replacement.exists()
        (destination / "manifest.sealed").write_bytes(original_manifest)
        model.write_bytes(b"changed")
        refused(
            lambda: recovery.restore(
                destination, replacement, "password", None, reconstruct=False
            ),
            "changed model",
        )
        model.write_bytes(b"external-model")
        payload = destination / "0.sealed"
        content = payload.read_bytes()
        payload.write_bytes(content[:-1])
        refused(
            lambda: recovery.restore(
                destination, replacement, "password", None, reconstruct=False
            ),
            "truncated state",
        )
        assert not replacement.exists()
        payload.write_bytes(content)
        recovery.restore(destination, replacement, "password", None, reconstruct=False)
        assert (replacement / recovery.MARKER).exists()
        assert (replacement / "state/client_keys.json").read_bytes() == (
            root / "client_keys.json"
        ).read_bytes()
        assert not (replacement / "state/logs").exists()
        refused(
            lambda: recovery.activate(replacement, original_stopped=False),
            "identity activated beside original",
        )
        refused(
            lambda: recovery.restore(
                destination, replacement, "password", None, reconstruct=False
            ),
            "overwrite existing destination",
        )
        refused(
            lambda: recovery.validate_restore(replacement),
            "wrong installed environment",
        )
        assert {
            str(p.relative_to(root)): recovery.digest(p)
            for p in root.rglob("*")
            if p.is_file()
        } == baseline
        if os.name != "nt":
            assert destination.stat().st_mode & 0o077 == 0
            assert replacement.stat().st_mode & 0o077 == 0
        print(
            "PASS encrypted round trip, revocations, SQLite, external assets, private directories, unchanged source"
        )


if __name__ == "__main__":
    run()
