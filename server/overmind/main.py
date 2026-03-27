"""Overmind server entry point: REST (FastAPI) + MCP (FastMCP) on single uvicorn."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from overmind.api import create_app
from overmind.mcp_server import create_mcp_server
from overmind.store import SQLiteStore


def create_standalone_app():
    """Factory for uvicorn --factory. Reads OVERMIND_DATA_DIR env var."""
    import os
    data_dir = Path(os.environ.get("OVERMIND_DATA_DIR", "data"))
    store = SQLiteStore(data_dir=data_dir)
    return create_app(data_dir=data_dir, store=store)


def main() -> None:
    parser = argparse.ArgumentParser(description="Overmind Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=7777, help="Bind port (default: 7777)")
    parser.add_argument("--data-dir", type=str, default="data", help="Data directory (default: data)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    store = SQLiteStore(data_dir=data_dir)

    # Create MCP app first to capture its lifespan
    mcp = create_mcp_server(store)
    mcp_app = mcp.http_app(path="/")

    app = create_app(data_dir=data_dir, store=store, lifespan=mcp_app.lifespan)

    # Mount MCP at /mcp
    app.mount("/mcp", mcp_app)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
