"""Run an actual Cline/Hermes/OpenClaw CLI against a harness-workbench candidate.

Client installations are explicit paths. Creates a fresh profile and task for
each run, keeps a fixture API key in the private profile or child environment, and
checks the task independently of the model's success claim. No messaging
channels are configured. Retain the transcript and observer log for review.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


CHECK = """from clamp import clamp
assert clamp(-2, 0, 10) == 0
assert clamp(12, 0, 10) == 10
assert clamp(4, 0, 10) == 4
assert clamp(-9, -8, -3) == -8
assert clamp(7, 7, 7) == 7
print("All clamp checks passed.")
"""
PROMPT = (
    "This is a confined API compatibility test. Work only in the current workspace. "
    "Use your file tools to read clamp.py and check.py. Fix only clamp.py so the function "
    "clamps values to the inclusive [low, high] interval. Do not edit check.py or any other "
    "file. Use no network, shell, delegation, or messaging tools. After editing, read "
    "clamp.py again with a tool and explain what changed. Do not claim tests were run: "
    "the acceptance runner will run them separately."
)


def run(args):
    record = json.loads((args.workbench / "run.json").read_text(encoding="utf-8"))
    root = args.directory.resolve()
    root.mkdir()
    task = root / "task"
    task.mkdir()
    profile = root / "profile"
    profile.mkdir()
    (task / "clamp.py").write_text(
        "def clamp(value, low, high):\n    return min(value, high)\n", encoding="utf-8"
    )
    (task / "check.py").write_text(CHECK, encoding="utf-8")
    (root / "prompt.txt").write_text(PROMPT, encoding="utf-8")
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(
            (
                "EUGENE_PLEXUS_",
                "OPENAI_",
                "OPENROUTER_",
                "ANTHROPIC_",
                "HERMES_",
                "OPENCLAW_",
                "CLINE_",
            )
        )
    }
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    model = record["model"]
    base = args.base_url or record["urls"]["gateway"] + "/v1"
    if args.client == "hermes":
        import yaml

        env.update(
            HERMES_HOME=str(profile),
            OPENAI_API_KEY=record["applicationKey"],
            OPENAI_BASE_URL=base,
        )
        config = {
            "model": {
                "provider": "custom",
                "base_url": base,
                "api_key": record["applicationKey"],
                "default": model,
                "context_length": 131072,
                "max_tokens": 4096,
            },
            "platform_toolsets": {"cli": ["file"]},
            "memory": {"memory_enabled": False, "user_profile_enabled": False},
            "compression": {"enabled": False},
            "agent": {"max_turns": 10},
        }
        (profile / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
        command = [
            str(args.cli.resolve()),
            "chat",
            "--cli",
            "--oneshot",
            "--ignore-rules",
            "--toolsets",
            "file",
            "--max-turns",
            "10",
            "--run-budget",
            "240",
            "--format",
            "stream-json",
            "--query-file",
            str(root / "prompt.txt"),
        ]
        if args.effort != "default":
            command += ["--reasoning", args.effort]
    elif args.client == "cline":
        assert args.node, "Cline needs --node"
        settings = profile / "settings"
        settings.mkdir()
        (settings / "providers.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "lastUsedProvider": "openai-compatible",
                    "modes": {},
                    "providers": {
                        "openai-compatible": {
                            "settings": {
                                "provider": "openai-compatible",
                                "apiKey": record["applicationKey"],
                                "model": model,
                                "baseUrl": base,
                            },
                            "tokenSource": "manual",
                            "updatedAt": "2026-10-15T00:00:00Z",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        command = [
            str(args.node.resolve()),
            str(args.cli.resolve()),
            "--data-dir",
            str(profile),
            "--config",
            str(profile),
            "--cwd",
            str(task),
            "--provider",
            "openai-compatible",
            "--model",
            model,
            "--json",
            "--timeout",
            "240",
            "--retries",
            "1",
            PROMPT,
        ]
        if args.effort != "default":
            command += ["--thinking", args.effort]
    else:
        assert args.node, "OpenClaw needs --node"
        env.update(
            OPENCLAW_STATE_DIR=str(profile),
            OPENCLAW_CONFIG_PATH=str(profile / "openclaw.json"),
            EUGENE_HARNESS_KEY=record["applicationKey"],
        )
        config = {
            "models": {
                "mode": "replace",
                "providers": {
                    "eugene": {
                        "baseUrl": base,
                        "apiKey": "${EUGENE_HARNESS_KEY}",
                        "api": "openai-completions",
                        "models": [
                            {
                                "id": model,
                                "name": model,
                                "reasoning": True,
                                "input": ["text"],
                                "contextWindow": 131072,
                                "maxTokens": 4096,
                                "compat": {
                                    "supportsUsageInStreaming": True,
                                    "supportsReasoningEffort": True,
                                },
                            }
                        ],
                    }
                },
            },
            "agents": {
                "defaults": {
                    "model": {"primary": "eugene/" + model},
                    "workspace": str(task),
                    "skipBootstrap": True,
                }
            },
            "tools": {
                "allow": ["read", "write", "edit"],
                "fs": {"workspaceOnly": True},
            },
        }
        (profile / "openclaw.json").write_text(
            json.dumps(config, indent=2), encoding="utf-8"
        )
        command = [
            str(args.node.resolve()),
            str(args.cli.resolve()),
            "agent",
            "--local",
            "--session-id",
            "eugene-acceptance",
            "--message-file",
            str(root / "prompt.txt"),
            "--json",
            "--timeout",
            "240",
        ]
        if args.effort != "default":
            command += ["--thinking", args.effort]
    started = time.perf_counter()
    with (root / "transcript.log").open("wb") as log:
        result = subprocess.run(
            command,
            cwd=task,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    checked = subprocess.run(
        [sys.executable, "check.py"], cwd=task, capture_output=True, text=True
    )
    report = {
        "client": args.client,
        "effort": args.effort,
        "clientExit": result.returncode,
        "elapsedSeconds": round(time.perf_counter() - started, 2),
        "checkUnchanged": (task / "check.py").read_text(encoding="utf-8") == CHECK,
        "taskCheckExit": checked.returncode,
        "taskCheck": checked.stdout.strip(),
    }
    (root / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    assert result.returncode == 0, "Client failed; inspect transcript.log"
    assert report["checkUnchanged"], "Client changed acceptance checks"
    assert checked.returncode == 0, "Task failed independent verification"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client", choices=["cline", "hermes", "openclaw"], required=True
    )
    parser.add_argument("--workbench", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--effort", default="default")
    run(parser.parse_args())
