"""Overmind server entry point: REST (FastAPI) + MCP (FastMCP) on single uvicorn."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from overmind.api import create_app
from overmind.mcp_server import create_mcp_server
from overmind.store import MemoryStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Overmind Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=7777, help="Bind port (default: 7777)")
    parser.add_argument("--data-dir", type=str, default="data", help="Data directory (default: data)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    store = MemoryStore(data_dir=data_dir)

    app = create_app(data_dir=data_dir, store=store)

    # Mount MCP at /mcp
    mcp = create_mcp_server(store)
    app.mount("/mcp", mcp.streamable_http_app())

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
