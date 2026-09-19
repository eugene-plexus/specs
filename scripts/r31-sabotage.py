"""R3.1 sabotage pass: the thinking filter, batch and streaming.

Roadmap §4 item 1, review §6.2 #21. Restores from a COPY, never
`git checkout --`, and opens with a baseline.

**The first two entries put the finding itself back**, one half each:
the batch pattern that did not know `<thinking>`, and the streaming
matcher with no word boundary that opened on it and then waited for a
`</think>` that never came. The rest take the fix apart one property at
a time -- the name read, the matching close, the unterminated tail, the
withheld prefix.

The gate is the whole driver suite, not just the new file: this module
is called by every engine on the `thinkingMode: off` path, and a
sabotage that only the new tests can see would not notice an engine
regressing.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")
DRIVER = "inference-driver"
THINKING = "src/eugene_plexus_inference_driver/engines/_thinking.py"

UNIT_TIMEOUT = 300


def run_gate() -> tuple[int, str]:
    try:
        py = ROOT / DRIVER / ".venv" / "Scripts" / "python.exe"
        done = subprocess.run(
            [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", "tests/"],
            cwd=ROOT / DRIVER,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=UNIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:]


SABOTAGES: list[tuple[str, str, str]] = [
    (
        "THE FINDING, batch half: `<thinking>` stops being a tag, so the span survives whole",
        r'_THINK_BLOCK_RE = re.compile(r"<(think(?:ing)?)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)',
        r'_THINK_BLOCK_RE = re.compile(r"<(think)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)',
    ),
    (
        "THE FINDING, streaming half: the close tag goes back to a literal `</think>`",
        'close = f"</{self._name}>"',
        'close = "</think>"',
    ),
    (
        "the open matcher loses its name read, so `<thinker>` opens a block again",
        "                if name.lower() not in _THINK_NAMES:",
        "                if False:",
    ),
    (
        "the name read stops waiting for the name to end, so `<think` decides too early",
        "                if not complete:\n                    # The name runs to the end of what we have; it may\n                    # yet become `thinking`. Withhold and wait.\n                    break",
        "                if False:\n                    break",
    ),
    (
        "an unterminated block leaks on the batch path, so the two paths disagree again",
        r'_THINK_TAIL_RE = re.compile(r"<think(?:ing)?\b.*$", re.DOTALL | re.IGNORECASE)',
        r'_THINK_TAIL_RE = re.compile(r"(?!x)x", re.DOTALL | re.IGNORECASE)',
    ),
    (
        "the tail is stripped BEFORE complete blocks, so it eats the answer after a closed block",
        '    cleaned = _THINK_TAIL_RE.sub("", _THINK_BLOCK_RE.sub("", text))',
        '    cleaned = _THINK_BLOCK_RE.sub("", _THINK_TAIL_RE.sub("", text))',
    ),
    (
        "flush stops distinguishing an undecided name from a real tag start",
        '        if state == "name":\n            read, _ = self._read_name(buf)\n            return "" if read.lower() in _THINK_NAMES else buf',
        '        if state == "name":\n            return ""',
    ),
    (
        "flush leaks an unterminated block instead of dropping it",
        '        if state in {"opening", "inside"}:\n            return ""',
        '        if state in {"opening", "inside"}:\n            return buf',
    ),
    (
        "the viable-prefix guard goes, so a tag split across chunks is emitted as text",
        "                    keep = self._viable_prefix_len(self._buf)",
        "                    keep = 0",
    ),
    (
        "the partial-close guard goes, so a `</think` split across chunks leaks the rest",
        "                    keep = min(len(self._buf), len(close) - 1)",
        "                    keep = 0",
    ),
    (
        "the open scan becomes case-sensitive, so `<THINK>` slips past streaming",
        "        lowered = text.lower()\n        index = lowered.find(cls._OPEN)",
        "        lowered = text\n        index = lowered.find(cls._OPEN)",
    ),
    (
        "a rejected name consumes the whole buffer rather than one character",
        "                    out.append(self._buf[0])\n                    self._buf = self._buf[1:]",
        "                    out.append(self._buf)\n                    self._buf = \"\"",
    ),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    backup = Path(tempfile.mkdtemp(prefix="r31-sabotage-"))
    dst = backup / THINKING
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / DRIVER / THINKING, dst)
    print(f"copy in {backup}\n")

    code, out = run_gate()
    print(f"[baseline] {DRIVER}: {'PASS' if code == 0 else 'FAIL'}")
    if code != 0:
        print(out)
        return 1
    print()

    path = ROOT / DRIVER / THINKING
    caught = escaped = 0
    for label, old, new in SABOTAGES:
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run_gate()
        finally:
            shutil.copy2(dst, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(SABOTAGES)} sabotages")
    code, out = run_gate()
    print(f"[restored] {DRIVER}: {'PASS' if code == 0 else 'FAIL'}")
    if code != 0:
        print(out)
        return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
