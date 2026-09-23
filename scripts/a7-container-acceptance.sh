#!/usr/bin/env bash
# Run against the image already built and checked by compose-acceptance.sh.
set -euo pipefail
work=$(mktemp -d)
name="ep-a7-recovery-$$"
trap 'docker rm -f "$name" >/dev/null 2>&1 || true; rm -rf "$work"' EXIT
mkdir -p "$work/models" "$work/engine"
curl -fL --retry 3 -o "$work/models/Qwen3-0.6B-Q4_K_M.gguf" \
  https://huggingface.co/unsloth/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q4_K_M.gguf
echo "ac2d97712095a558e31573f62f466a3f9d93990898b0ec79d7c974c1780d524a  $work/models/Qwen3-0.6B-Q4_K_M.gguf" | sha256sum -c -
curl -fL --retry 3 -o "$work/engine.tar.gz" \
  https://github.com/ggml-org/llama.cpp/releases/download/b11065/llama-b11065-bin-ubuntu-x64.tar.gz
echo "f00971c1b044fae179230bfc6f8d9f8461b778fef9ffac2b450088081a8ecd43  $work/engine.tar.gz" | sha256sum -c -
tar -xzf "$work/engine.tar.gz" -C "$work/engine"
# Run on the image that gets published, unmodified. Until 2026-09-23 this
# built a disposable derivative that added libgomp1, because the production
# image could not start a llama-server at all; the image carries it now, so
# this check is also the proof that it can serve a real completion.
chmod -R a+rX "$work/models" "$work/engine"
docker run --name "$name" --init \
  --mount "type=bind,src=$PWD/scripts,dst=/instruments,readonly" \
  --mount "type=bind,src=$work/models,dst=/fixture-models,readonly" \
  --mount "type=bind,src=$work/engine,dst=/fixture-engine,readonly" \
  --entrypoint /opt/eugene-plexus/venv/bin/python \
  eugene-plexus/control-plane:0.1 /instruments/a7-recovery-acceptance.py \
  --directory /tmp/a7-run --disposable-venv /opt/eugene-plexus/venv \
  --uv /opt/eugene-plexus/bin/uv \
  --model /fixture-models/Qwen3-0.6B-Q4_K_M.gguf \
  --engine /fixture-engine/llama-b11065/llama-server
docker cp "$name:/tmp/a7-run/result.json" "$work/result.json"
cat "$work/result.json"
