"""Sabotage pass: images on the Anthropic door.

2026-09-23. Restores from a COPY, never `git checkout --`, and opens with
a baseline on the gate (feedback memory: a restore that reverts
uncommitted work deletes the change under test, and every later result
reads *caught* for the wrong reason).

One repo: the translation is the gateway's, and the driver already
carries image parts from the OpenAI door.

Three kinds of sabotage, as in r34-sabotage.py: put the finding back,
put the over-correction in, and take the discriminator apart. The
over-corrections this change invites are specific:

* leave a tool's picture on the `tool` message, or after the person's
  words, or with nothing saying which call it came from;
* accept an image on an assistant turn, or a URL source;
* pass a GIF or WebP through as itself, or refuse it outright;
* count the image limit per block instead of per request;
* stop joining adjacent text blocks, which changes every text request.

An escape means the check set cannot tell the fix from its opposite.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")
UNIT_TIMEOUT = 900

GATEWAY = "gateway"
ANTHROPIC = "src/eugene_plexus_gateway/anthropic.py"
IMAGES = "src/eugene_plexus_gateway/images.py"

FILES = {GATEWAY: (ANTHROPIC, IMAGES)}

GATES = {
    GATEWAY: (
        "tests/test_anthropic_images.py",
        "tests/test_anthropic_messages.py",
        "tests/test_images.py",
        "tests/test_chat_contract.py",
        "tests/test_reasoning_and_local_samplers.py",
        "tests/test_tool_calling.py",
    ),
}


def run_gate(repo: str) -> tuple[int, str]:
    py = ROOT / repo / ".venv" / "Scripts" / "python.exe"
    try:
        done = subprocess.run(
            [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", *GATES[repo]],
            cwd=ROOT / repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=UNIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:]


# (label, repo, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # --------------------------------------------------------------- #
    # the finding, put back
    # --------------------------------------------------------------- #
    (
        "THE FINDING: image blocks refused again",
        GATEWAY,
        ANTHROPIC,
        '_REFUSED_BLOCK_TYPES = {"document"}',
        '_REFUSED_BLOCK_TYPES = {"image", "document"}',
    ),
    (
        "a user's image block silently dropped",
        GATEWAY,
        ANTHROPIC,
        "                parts.append(_image_part(block, where, budget))\n",
        "                pass\n",
    ),
    (
        "THE FINDING, Claude Code's shape: a tool result's pictures dropped",
        GATEWAY,
        ANTHROPIC,
        "                pictures = _tool_result_images(block, where, budget)\n",
        "                pictures = []\n",
    ),
    # --------------------------------------------------------------- #
    # where a tool's picture goes
    # --------------------------------------------------------------- #
    (
        "a tool's picture placed after the person's words",
        GATEWAY,
        ANTHROPIC,
        "        content = _joined(hoisted + parts)\n",
        "        content = _joined(parts + hoisted)\n",
    ),
    (
        "the tool message no longer says where its picture went",
        GATEWAY,
        ANTHROPIC,
        '                    text = f"{text}\\n{note}" if text else note\n',
        "                    text = text\n",
    ),
    (
        "the picture no longer names the call it came from",
        GATEWAY,
        ANTHROPIC,
        'type="text", text=f"{label} returned by tool call {call_id}:"',
        'type="text", text=f"{label}:"',
    ),
    (
        "a tool's error flag lost beside its picture",
        GATEWAY,
        ANTHROPIC,
        "                text = _tool_result_text(block)\n",
        '                text = _tool_result_text(block).removeprefix("[tool error]").strip()\n',
    ),
    # --------------------------------------------------------------- #
    # the over-corrections
    # --------------------------------------------------------------- #
    (
        "an image accepted on an assistant turn",
        GATEWAY,
        ANTHROPIC,
        '                if role != "user":\n                    raise Refusal(\n'
        '                        f"{where}: images are accepted',
        '                if False:\n                    raise Refusal(\n'
        '                        f"{where}: images are accepted',
    ),
    (
        "a URL source let through",
        GATEWAY,
        ANTHROPIC,
        'source.get("type") != "base64":',
        'source.get("type") not in ("base64", "url"):',
    ),
    (
        "GIF and WebP passed through as themselves",
        GATEWAY,
        IMAGES,
        'if media_type in ("image/png", "image/jpeg"):',
        'if media_type in ("image/png", "image/jpeg", "image/gif", "image/webp"):',
    ),
    (
        "GIF and WebP refused outright",
        GATEWAY,
        IMAGES,
        '_REENCODED = {"image/gif": "GIF", "image/webp": "WEBP"}',
        "_REENCODED: dict[str, str] = {}",
    ),
    (
        "an animated GIF flattened to its first frame",
        GATEWAY,
        IMAGES,
        '                if getattr(picture, "is_animated", False):\n'
        '                    raise ImageRefusal(field, "animated images are not supported")\n'
        "                out = io.BytesIO()\n",
        "                out = io.BytesIO()\n",
    ),
    (
        "the re-encode skipped: original bytes labelled PNG",
        GATEWAY,
        IMAGES,
        '                picture.save(out, format="PNG")\n',
        "                out.write(raw)\n",
    ),
    # --------------------------------------------------------------- #
    # the limits and the checks, taken apart
    # --------------------------------------------------------------- #
    (
        "the image limit counted per block, not per request",
        GATEWAY,
        ANTHROPIC,
        "        budget.admit(url, field)\n",
        "        images.ImageBudget().admit(url, field)\n",
    ),
    (
        "a picture never checked against what it claims to be",
        GATEWAY,
        ANTHROPIC,
        "        budget.admit(url, field)\n",
        "        pass\n",
    ),
    (
        "the OpenAI door's limit counted per message part (the shared budget)",
        GATEWAY,
        IMAGES,
        '            budget.admit(part["image_url"]["url"], field)\n',
        '            ImageBudget().admit(part["image_url"]["url"], field)\n',
    ),
    (
        "refusals name the turn, not the block",
        GATEWAY,
        ANTHROPIC,
        '            where = f"messages.{turn_index}.content.{block_index}"\n',
        '            where = f"messages.{turn_index}"\n',
    ),
    (
        "a nested picture named at its tool result, not itself",
        GATEWAY,
        ANTHROPIC,
        '        _image_part(inner, f"{where}.content.{i}", budget)\n',
        "        _image_part(inner, where, budget)\n",
    ),
    (
        "adjacent text blocks no longer joined",
        GATEWAY,
        ANTHROPIC,
        "        if isinstance(part, TextContentPart) and isinstance(previous, TextContentPart):\n",
        "        if False:\n",
    ),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    backup = Path(tempfile.mkdtemp(prefix="anthropic-images-sabotage-"))
    for repo, relatives in FILES.items():
        for relative in relatives:
            destination = backup / repo / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / repo / relative, destination)
    print(f"copy in {backup}\n")

    for repo in FILES:
        code, out = run_gate(repo)
        print(f"[baseline] {repo}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    print()

    wanted = [s for s in SABOTAGES if not sys.argv[1:] or any(a in s[0] for a in sys.argv[1:])]
    caught = escaped = 0
    for label, repo, relative, old, new in wanted:
        path = ROOT / repo / relative
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {repo}: {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run_gate(repo)
        finally:
            shutil.copy2(backup / repo / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {repo}: {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {repo}: {label}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(wanted)} sabotages")
    ok = True
    for repo in FILES:
        code, out = run_gate(repo)
        print(f"[restored] {repo}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            ok = False
    if not ok:
        return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
