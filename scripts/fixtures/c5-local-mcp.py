"""Runner-only MCP server: inspect actual OS access without returning file contents."""

import os
import subprocess
import sys
from pathlib import Path

from mcp.server import MCPServer

from app_probe import _probe

server = MCPServer("C5 account probe", log_level="ERROR")


@server.tool()
def inspect_account() -> dict:
    """Report this process's account and which Eugene files it can read."""
    result = _probe(sys.argv[1])
    # Return only unexpected readable names; a full venv listing can exceed
    # the tool result bound. No file contents are ever returned.
    allowed = (
        "apps/workbench/",
        "venv/",
        "pythons/",
        "bin/",
        "ui/",
        "apps/pythons/",
        "apps/launcher/",
    )
    result["readable"] = [p for p in result["readable"] if not p.startswith(allowed)]
    result["eugeneEnvironment"] = sorted(
        k for k in os.environ if k.startswith("EUGENE_PLEXUS_")
    )
    result["cwd"] = os.getcwd()
    result["home"] = os.environ.get("HOME")
    result["explicitValue"] = (
        os.environ.get("C5_MARKER") == "configured-for-this-server"
    )
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    result["serverPid"], result["childPid"] = os.getpid(), child.pid
    Path("approved-call.txt").write_text("called", encoding="utf-8")
    return result


server.run()
