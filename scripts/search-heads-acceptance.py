"""Compare Library and agent decisions on four real Search-model GGUF headers.

Reads metadata and tensor tables only. No weights are loaded or executed.
Run from an environment containing both components, with --model-dir naming
the existing acceptance-models folder.
"""

import argparse
from pathlib import Path

from eugene_plexus_agent.engines.run_mode import resolve
from eugene_plexus_library.formats.gguf import read_metadata


def check(folder: Path) -> None:
    cases = (
        ("bge-reranker-v2-m3-Q8_0.gguf", "reranking"),
        ("qwen3-reranker-0.6b-q8_0.gguf", "reranking"),
        ("Qwen3-Embedding-0.6B-Q8_0.gguf", "embedding"),
        ("nomic-embed-text-v1.5.Q8_0.gguf", "embedding"),
    )
    for name, expected in cases:
        path = folder / name
        meta = read_metadata(path, tensors=True)
        decision = resolve("auto", str(path))
        predicted = (
            "reranking"
            if meta.is_rerank
            else "embedding"
            if meta.is_embedding
            else "chat"
        )
        assert predicted == decision.task == expected, (name, predicted, decision)
        print(
            f"PASS {name}: Library and agent say {expected}; {decision.why}", flush=True
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    check(parser.parse_args().model_dir)
