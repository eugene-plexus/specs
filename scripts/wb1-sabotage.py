"""Sabotage for workbench#1: text written before a web search is a draft,
folded on the page and not sent back as history.

Each sabotage edits Workbench's source, runs the tests that should catch it
(pytest for the server, vitest for the page), and restores the file from a
byte copy taken first. A baseline run of both that must pass opens it. A
timeout counts as caught.

    python scripts/wb1-sabotage.py [--workbench ../workbench]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ANSWERS = "src/eugene_plexus_workbench/answers.py"
CONVERSATION = "src/eugene_plexus_workbench/conversation.py"
STORE = "src/eugene_plexus_workbench/store.py"
WORDS = "web/src/lib/words.ts"
USECHAT = "web/src/lib/useChat.ts"
VIEW = "web/src/components/MessageView.tsx"

PY_TESTS = ["tests/test_chats.py", "tests/test_store_schema.py"]

# (name, file, old, new, which suite catches it)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    (
        "a search's progress marks nothing",
        ANSWERS,
        "                    m.answer_from, m.reasoning_from = len(m.content), len(m.reasoning)\n",
        "",
        "py",
    ),
    (
        "only a progress with phase 'finished' marks",
        ANSWERS,
        'if progress.get("stage") == "tool" and progress.get("tool") == "web_search":',
        'if progress.get("stage") == "tool" and progress.get("phase") == "finished":',
        "py",
    ),
    (
        "the whole reply goes back as history",
        CONVERSATION,
        '"content": answer_text(message)})',
        '"content": message.content})',
        "py",
    ),
    (
        "the answer keeps the gateway's paragraph break",
        ANSWERS,
        "    after = message.content[message.answer_from :].lstrip()",
        "    after = message.content[message.answer_from :]",
        "py",
    ),
    (
        "nothing after the search means no answer at all",
        ANSWERS,
        "    return after or message.content",
        "    return after",
        "py",
    ),
    (
        "the page is given Python's string length",
        ANSWERS,
        "    return None if index is None else _js_length(text[:index])",
        "    return index",
        "py",
    ),
    (
        "the marks are not saved",
        ANSWERS,
        '            "answer_from": m.answer_from,\n',
        "",
        "py",
    ),
    (
        "an old store is not migrated",
        STORE,
        '        "ALTER TABLE messages ADD COLUMN answer_from INTEGER",\n',
        "",
        "py",
    ),
    (
        "the page ignores a search's mark",
        USECHAT,
        "      if (event.answerFrom === undefined) return { detail, gap: false };",
        "      return { detail, gap: false };",
        "web",
    ),
    (
        "a reply that stopped after its search shows nothing",
        WORDS,
        '  if (!answer && message.status !== "running") return { draft: "", answer: message.content };\n',
        "",
        "web",
    ),
    (
        "the draft is shown open",
        VIEW,
        '          data-testid="draft"\n',
        '          data-testid="draft"\n          open\n',
        "web",
    ),
    (
        "waiting is judged by the whole text",
        VIEW,
        '  const waiting = message.status === "running" && !answer;',
        '  const waiting = message.status === "running" && !message.content;',
        "web",
    ),
    (
        "Copy copies the draft too",
        VIEW,
        "onClick={() => void navigator.clipboard?.writeText(answer)}",
        "onClick={() => void navigator.clipboard?.writeText(message.content)}",
        "web",
    ),
    (
        "the reasoning is not split at the search",
        WORDS,
        "  if (at == null) return [message.reasoning];",
        "  return [message.reasoning];",
        "web",
    ),
    (
        "the finished search reads as still searching",
        WORDS,
        '"Reading what the search found…"',
        '"Searching the web…"',
        "web",
    ),
]


def python_of(workbench: Path) -> str:
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
        if (workbench / rel).exists():
            return str(workbench / rel)
    raise SystemExit("no .venv in the Workbench checkout")


def run(workbench: Path, suite: str) -> bool:
    if suite == "py":
        cmd, cwd = [python_of(workbench), "-m", "pytest", "-q", "-x", *PY_TESTS], workbench
    else:
        npx = "npx.cmd" if os.name == "nt" else "npx"
        cmd, cwd = [npx, "vitest", "run"], workbench / "web"
    try:
        done = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return False
    return done.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workbench", type=Path, default=Path(__file__).resolve().parents[2] / "workbench"
    )
    workbench = parser.parse_args().workbench.resolve()
    for suite in ("py", "web"):
        if not run(workbench, suite):
            print(f"BASELINE FAILED ({suite}): the tests do not pass unsabotaged")
            return 2
    print("baseline passes")
    caught = 0
    for name, rel, old, new, suite in SABOTAGES:
        path = workbench / rel
        original = path.read_bytes()
        text = original.decode("utf-8")
        if "\r\n" in text:  # a Windows checkout
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
        if text.count(old) != 1:
            print(f"NOT APPLIED ({text.count(old)} matches): {name}")
            return 2
        try:
            path.write_bytes(text.replace(old, new).encode("utf-8"))
            passed = run(workbench, suite)
        finally:
            path.write_bytes(original)
        caught += not passed
        print(f"{'CAUGHT ' if not passed else 'ESCAPED'} {name}")
    print(f"{caught}/{len(SABOTAGES)} caught")
    return 0 if caught == len(SABOTAGES) else 1


if __name__ == "__main__":
    sys.exit(main())
