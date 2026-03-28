#!/usr/bin/env bash
# Overmind server (REST + MCP + dashboard) on port 7777.
# See docs/local-testing-guide.md and CLAUDE.md (How to Run).
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --all-extras
exec uv run python -m overmind.main --port 7777
