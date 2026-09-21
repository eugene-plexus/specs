"""Run a confined, real Claude Code task against an A4 isolated workbench.

Requires Claude Code 2.1.207 and the Python used by the workbench. Creates a new
coding-task directory; refuses to overwrite an earlier run. Credentials are read
from run.json, passed through the environment, and never printed. --base-url may
select the transparent observer; otherwise the real gateway is used directly.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess


def run(args):
    root = args.directory.resolve()
    record = json.loads((root / "run.json").read_text(encoding="utf-8"))
    task = root / "coding-task"
    task.mkdir()  # An existing task is evidence, not something to reset.
    subprocess.run(["git", "init", "--quiet", str(task)], check=True)
    (task / "clamp.py").write_text(
        "def clamp(value, low, high):\n"
        '    """Keep a value within the inclusive low/high interval."""\n'
        "    return min(value, high)\n",
        encoding="utf-8",
    )
    check = (
        "from clamp import clamp\n"
        "assert clamp(-2, 0, 10) == 0\n"
        "assert clamp(12, 0, 10) == 10\n"
        "assert clamp(4, 0, 10) == 4\n"
        'print("All clamp checks passed.")\n'
    )
    (task / "check.py").write_text(check, encoding="utf-8")
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("ANTHROPIC_", "CLAUDE_", "EUGENE_PLEXUS_"))
    }
    env.update(
        {
            "CLAUDE_CONFIG_DIR": str(root / "claude-config"),
            "ANTHROPIC_API_KEY": record["applicationKey"],
            "ANTHROPIC_BASE_URL": args.base_url or record["urls"]["gateway"],
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_TELEMETRY": "1",
            "ANTHROPIC_CUSTOM_MODEL_OPTION": "a4-vision",
            "ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES": "thinking",
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "16384",
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "2048",
            "MAX_THINKING_TOKENS": "0",
            "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING": "1",
            "CLAUDE_CODE_EFFORT_LEVEL": "unset",
            "PYTHONUTF8": "1",
        }
    )
    command = [
        str(args.cli.resolve()),
        "--bare",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--setting-sources",
        "",
        "--model",
        "a4-vision",
        "--tools",
        "Read,Edit,Bash",
        "--allowedTools",
        "Read(./clamp.py)",
        "Read(./check.py)",
        "Edit(./clamp.py)",
        "Bash(python check.py)",
        "--system-prompt",
        "Complete the small coding task. Read only clamp.py and check.py, edit only "
        "clamp.py, and run only python check.py. Explain your change and check result.",
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-turns",
        "10",
    ]

    def invoke(label, prompt, session=None):
        cmd = command + (["--resume", session] if session else []) + ["-p", prompt]
        with (root / f"{label}.jsonl").open("wb") as log:
            subprocess.run(
                cmd,
                cwd=task,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=660,
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        rows = [
            json.loads(line)
            for line in (root / f"{label}.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        result = next(row for row in reversed(rows) if row.get("type") == "result")
        assert not result.get("is_error"), (
            f"Inspect {label}.jsonl for the client failure"
        )
        assert not result.get("permission_denials"), (
            "The task exceeded its allowed tools"
        )
        print(
            label, "completed; inspect the local transcript for model-quality evidence."
        )
        return result

    first = invoke(
        "claude-local",
        "Inspect clamp.py and check.py. Explain the smallest fix, "
        "apply it only to clamp.py, and run python check.py. Do not edit check.py.",
    )
    invoke(
        "claude-followup",
        "Explain the result below, between and above the bounds. "
        "Re-run python check.py. Do not change any files.",
        first["session_id"],
    )
    assert (task / "check.py").read_text(encoding="utf-8") == check
    print(
        "Review both transcripts and the diff: client success alone is not task acceptance."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--base-url")
    run(parser.parse_args())
