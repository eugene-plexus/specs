"""release-inputs.py's checks on release/manifest.json, offline (row 42)."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("release_inputs", SCRIPTS / "release-inputs.py")
assert _spec is not None and _spec.loader is not None
release_inputs = importlib.util.module_from_spec(_spec)
sys.modules["release_inputs"] = release_inputs
_spec.loader.exec_module(release_inputs)

MANIFEST = json.loads((SCRIPTS.parent / "release" / "manifest.json").read_text(encoding="utf-8"))


class VllmImageTests(unittest.TestCase):
    def test_the_vllm_image_is_pinned_by_digest(self) -> None:
        images = MANIFEST["vllmImages"]
        self.assertEqual({"cuda", "cuda12", "rocm"}, set(images))
        for variant, pinned in images.items():
            with self.subTest(variant=variant):
                self.assertRegex(pinned["image"], r"^[a-z0-9./_-]+@sha256:[0-9a-f]{64}$")
                self.assertRegex(pinned["version"], r"^\d+\.\d+\.\d+$")
        release_inputs.check_vllm_images(MANIFEST)

    def test_a_moving_tag_is_refused(self) -> None:
        moved = copy.deepcopy(MANIFEST)
        moved["vllmImages"]["cuda"]["image"] = "vllm/vllm-openai:latest"
        with self.assertRaisesRegex(ValueError, "by digest"):
            release_inputs.check_vllm_images(moved)

    def test_a_missing_variant_is_refused(self) -> None:
        moved = copy.deepcopy(MANIFEST)
        del moved["vllmImages"]["cuda12"]
        with self.assertRaisesRegex(ValueError, "cuda12"):
            release_inputs.check_vllm_images(moved)

    def test_a_manifest_from_before_row_42_pins_none_and_passes(self) -> None:
        """A patch line cut from v0.7.0 carries a manifest with no images."""
        older = copy.deepcopy(MANIFEST)
        del older["vllmImages"]
        release_inputs.check_vllm_images(older)


if __name__ == "__main__":
    unittest.main()
