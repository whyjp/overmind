# Overmind server (REST + MCP + dashboard) on port 7777.
# See docs/local-testing-guide.md and CLAUDE.md (How to Run).
Set-Location (Join-Path $PSScriptRoot '..')
uv sync --all-extras
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run python -m overmind.main --port 7777
