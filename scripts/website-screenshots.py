"""Photograph the real console for eugeneplexus.com.

The website shows the product, and the pictures should be the product: this
runs S9's isolated install (real packaged UI, real components, a real CPU
model through llama.cpp, random free ports, no ambient EUGENE_PLEXUS_*), then
`website-screenshots.mjs` drives Chrome through Home, a first reply, Discover
and a phone-width Home, and saves PNGs into --output. Nothing is intercepted
or canned; nothing touches an installed service.

    python scripts/website-screenshots.py --output <new-dir> \
        --engine <llama-server> --model <small chat GGUF, e.g. Qwen3-0.6B>

The model is served as `qwen3-0.6b` with the driver's thinking mode off, so
the reply on screen is an answer rather than a reasoning trace. Review every
image before publishing it: the Home strip names this machine's hardware.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _s9():
    spec = importlib.util.spec_from_file_location("s9_ui_acceptance", HERE / "s9-ui-acceptance.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    _s9().check(
        args.output.resolve(),
        args.engine.resolve(),
        args.model.resolve(),
        browser=HERE / "website-screenshots.mjs",
        alias="qwen3-0.6b",
        driver={"thinkingMode": "off"},
    )
