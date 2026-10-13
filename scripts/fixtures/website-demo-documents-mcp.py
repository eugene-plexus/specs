"""A tiny MCP server over the demo documents folder, for the website screenshots.

Run with Workbench's interpreter (it has the MCP SDK):

    website-demo-documents-mcp.py <folder> <port>

It serves two read-only tools over streamable HTTP on 127.0.0.1: list the
files in the folder, and read one text file. It exists because Workbench's own
folder tools need Workbench to run as its own OS account, which a disposable
per-user install does not have; an MCP server's calls are held for approval
the same way.
"""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn
from mcp.server.mcpserver import MCPServer

folder = Path(sys.argv[1]).resolve()
server = MCPServer("Documents folder")


@server.tool()
def list_files() -> str:
    """List the files in the documents folder."""
    return "\n".join(sorted(p.name for p in folder.iterdir() if p.is_file()))


@server.tool()
def read_file(name: str) -> str:
    """Read one text file (such as a CSV) from the documents folder."""
    target = (folder / name).resolve()
    if (
        target.parent != folder
        or not target.is_file()
        or target.suffix.lower() not in {".csv", ".txt", ".md"}
    ):
        return "That file is not available."
    return target.read_text(encoding="utf-8")[:8000]


if __name__ == "__main__":
    uvicorn.run(
        server.streamable_http_app(),
        host="127.0.0.1",
        port=int(sys.argv[2]),
        log_level="warning",
    )
