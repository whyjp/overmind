import pytest
from pathlib import Path

# Tests run from plugin/ directory, scripts/ is importable
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from context_writer import write_context_file


def _make_events():
    return [
        {"type": "correction", "result": "Use argon2 instead of bcrypt", "user": "dev_a",
         "ts": "2026-03-27T10:00:00Z", "scope": "src/auth/*", "summary": None},
        {"type": "decision", "result": "All API endpoints must validate input", "user": "dev_b",
         "ts": "2026-03-27T11:00:00Z", "scope": "src/api/*", "summary": "Validate all API input"},
        {"type": "discovery", "result": "Redis v3 pub/sub has memory leak", "user": "dev_a",
         "ts": "2026-03-27T12:00:00Z", "scope": "src/services/*", "summary": None},
        {"type": "change", "result": "Migrated auth to custom middleware", "user": "dev_a",
         "ts": "2026-03-27T09:00:00Z", "scope": "src/auth/*", "summary": None},
    ]


class TestWriteContextFile:
    def test_writes_grouped_by_type(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        write_context_file(_make_events(), output)
        content = output.read_text(encoding="utf-8")

        # Check section order: corrections before decisions before discoveries before changes
        corr_pos = content.index("## Corrections")
        dec_pos = content.index("## Decisions")
        disc_pos = content.index("## Discoveries")
        chg_pos = content.index("## Changes")
        assert corr_pos < dec_pos < disc_pos < chg_pos

    def test_empty_groups_omitted(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        events = [e for e in _make_events() if e["type"] == "correction"]
        write_context_file(events, output)
        content = output.read_text(encoding="utf-8")

        assert "## Corrections" in content
        assert "## Decisions" not in content
        assert "## Discoveries" not in content
        assert "## Changes" not in content

    def test_uses_summary_over_result(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        write_context_file(_make_events(), output)
        content = output.read_text(encoding="utf-8")

        # decision event has summary="Validate all API input"
        assert "Validate all API input" in content
        # correction event has no summary, uses result
        assert "Use argon2 instead of bcrypt" in content

    def test_scope_omitted_when_none(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        events = [{"type": "correction", "result": "No scope event", "user": "dev_a",
                    "ts": "2026-03-27T10:00:00Z", "scope": None, "summary": None}]
        write_context_file(events, output)
        content = output.read_text(encoding="utf-8")

        assert "No scope event (dev_a, 2026-03-27)" in content
        assert "scope:" not in content

    def test_creates_parent_directory(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        assert not output.parent.exists()
        write_context_file(_make_events(), output)
        assert output.exists()

    def test_header_contains_metadata(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        write_context_file(_make_events(), output)
        content = output.read_text(encoding="utf-8")

        assert "# Overmind Team Context" in content
        assert "Auto-synced at session start" in content
        assert "Events: 4" in content

    def test_empty_events_does_nothing(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        write_context_file([], output)
        assert not output.exists()

    def test_overwrites_existing_file(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        output.parent.mkdir(parents=True)
        output.write_text("old content", encoding="utf-8")

        write_context_file(_make_events(), output)
        content = output.read_text(encoding="utf-8")
        assert "old content" not in content
        assert "# Overmind Team Context" in content
