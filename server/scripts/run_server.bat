@echo off
REM Overmind server (REST + MCP + dashboard) on port 7777.
REM See docs/local-testing-guide.md and CLAUDE.md (How to Run).
cd /d "%~dp0.."
uv sync --all-extras
if errorlevel 1 exit /b 1
uv run python -m overmind.main --port 7777
