#!/usr/bin/env python3
"""Where does each request stop being a continuation of the one before it?

Reads a JSONL capture from `prompt-cache-capture.py` (or any file of
`{"path", "body"}` lines) and, for each request that offers tools, finds the
first point at which it differs from the previous such request. A prompt
cache can reuse a request's prefix only up to that point, so this is the
ceiling on what any engine can reuse, before the engine or Eugene has done
anything at all.

The comparison is over the request as the client sent it, in order: system
blocks, then tool definitions, then each message's parts. `cache_control` is
left out, because it marks a breakpoint and is not prompt text.

    python prompt-cache-prefix.py run.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def segments(body: dict) -> list[tuple[str, str]]:
    """The request, as a list of (label, text) in the order a template reads it."""
    out: list[tuple[str, str]] = []
    if "messages" in body:  # Anthropic Messages or chat completions
        system = body.get("system")
        if isinstance(system, str):
            out.append(("system[0]", system))
        elif isinstance(system, list):
            for i, block in enumerate(system):
                out.append((f"system[{i}]", block.get("text", json.dumps(_strip(block)))))
        for i, tool in enumerate(body.get("tools") or []):
            out.append((f"tool[{i}]:{tool.get('name') or tool.get('function', {}).get('name')}",
                        json.dumps(_strip(tool), sort_keys=False)))
        for i, message in enumerate(body.get("messages") or []):
            # A text part and a string carry the same prompt text: clients send
            # the newest message as parts (to hang `cache_control` on it) and
            # the same message as a string a turn later.
            content = message.get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            for j, part in enumerate(content or []):
                text = part.get("text") if part.get("type") == "text" else None
                out.append((f"msg[{i}].{message.get('role')}[{j}]",
                            text if text is not None else json.dumps(_strip(part), sort_keys=False)))
    else:  # OpenAI Responses
        if body.get("instructions"):
            out.append(("instructions", body["instructions"]))
        for i, tool in enumerate(body.get("tools") or []):
            out.append((f"tool[{i}]:{tool.get('name') or tool.get('type')}",
                        json.dumps(_strip(tool), sort_keys=False)))
        items = body.get("input")
        if isinstance(items, str):
            out.append(("input", items))
        for i, item in enumerate(items if isinstance(items, list) else []):
            out.append((f"input[{i}].{item.get('type') or item.get('role')}",
                        json.dumps(_strip(item), sort_keys=False)))
    return out


def first_difference(a: list[tuple[str, str]], b: list[tuple[str, str]]):
    """(segment index, char offset in it, chars of a that b shares) or None if a is a prefix of b."""
    shared = 0
    for i, (left, right) in enumerate(zip(a, b)):
        if left == right:
            shared += len(left[1])
            continue
        lt, rt = left[1], right[1]
        k = 0
        while k < min(len(lt), len(rt)) and lt[k] == rt[k]:
            k += 1
        return i, k, shared + k
    if len(a) <= len(b):
        return None
    return len(b), 0, shared


def main() -> None:
    lines = [json.loads(x) for x in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if x]
    posts = [x for x in lines if x.get("body")]
    for x in posts:
        b = x["body"]
        segs = segments(b)
        total = sum(len(t) for _, t in segs)
        print(f"#{x['n']:>2} {x['path']:<28} model={b.get('model')!s:<22} tools={len(b.get('tools') or []):>3} "
              f"segs={len(segs):>3} chars={total:>7} key={b.get('prompt_cache_key')!s:.40}")
    print()
    main_ = [x for x in posts if x["body"].get("tools")]
    for prev, cur in zip(main_, main_[1:]):
        a, b = segments(prev["body"]), segments(cur["body"])
        diff = first_difference(a, b)
        total = sum(len(t) for _, t in a)
        if diff is None:
            print(f"#{prev['n']} -> #{cur['n']}: a strict continuation ({total} chars reusable)")
            continue
        i, k, shared = diff
        la = a[i] if i < len(a) else ("<end>", "")
        lb = b[i] if i < len(b) else ("<end>", "")
        print(f"#{prev['n']} -> #{cur['n']}: differs at segment {i} {la[0]!r} vs {lb[0]!r}, char {k}; "
              f"{shared} of {total} chars ({100 * shared / max(total, 1):.1f}%) reusable")
        print(f"    before: {la[1][max(0, k - 60):k + 80]!r}")
        print(f"    after:  {lb[1][max(0, k - 60):k + 80]!r}")


if __name__ == "__main__":
    main()
