"""Tests for plugin/scripts/formatter.py output formatting."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from formatter import format_session_start, format_pre_tool_use


class TestFormatSessionStart:
    def test_empty_events_returns_none(self):
        assert format_session_start([]) is None

    def test_correction_in_rules_section(self):
        events = [{
            "type": "correction",
            "user": "dev_a",
            "result": "bcrypt to argon2",
            "priority": "normal",
            "process": ["perf issue found"],
        }]
        msg = format_session_start(events)
        assert "RULES" in msg
        assert "bcrypt to argon2" in msg
        assert "dev_a" in msg
        assert "Reason: perf issue found" in msg

    def test_decision_in_rules_section(self):
        events = [{"type": "decision", "user": "dev_b", "result": "use Redis", "priority": "normal", "process": []}]
        msg = format_session_start(events)
        assert "RULES" in msg
        assert "use Redis" in msg

    def test_discovery_in_context_section(self):
        events = [{"type": "discovery", "user": "dev_a", "result": "found endpoint", "priority": "normal"}]
        msg = format_session_start(events)
        assert "CONTEXT" in msg
        assert "found endpoint" in msg

    def test_broadcast_in_announcements_section(self):
        events = [{"type": "broadcast", "user": "master", "result": "deploy freeze", "priority": "normal"}]
        msg = format_session_start(events)
        assert "ANNOUNCEMENTS" in msg
        assert "deploy freeze" in msg

    def test_high_priority_prefix(self):
        events = [{"type": "correction", "user": "dev_a", "result": "fix it", "priority": "high_priority", "process": []}]
        msg = format_session_start(events)
        assert "[HIGH PRIORITY]" in msg

    def test_mixed_events(self):
        events = [
            {"type": "correction", "user": "dev_a", "result": "rule1", "priority": "normal", "process": []},
            {"type": "discovery", "user": "dev_b", "result": "context1", "priority": "normal"},
            {"type": "broadcast", "user": "master", "result": "announce1", "priority": "normal"},
        ]
        msg = format_session_start(events)
        assert "RULES" in msg
        assert "CONTEXT" in msg
        assert "ANNOUNCEMENTS" in msg

    def test_header_present(self):
        events = [{"type": "discovery", "user": "dev_a", "result": "something", "priority": "normal"}]
        msg = format_session_start(events)
        assert "[OVERMIND]" in msg

    def test_footer_present(self):
        events = [{"type": "discovery", "user": "dev_a", "result": "something", "priority": "normal"}]
        msg = format_session_start(events)
        assert "Follow RULES strictly" in msg

    def test_change_with_diff_in_fixes_section(self):
        """Events containing diffs should appear in FIXES section, not CONTEXT."""
        events = [{
            "type": "change",
            "user": "pioneer",
            "result": "Modified config.toml (1 file: config.toml)\nDiff:\n+[server]\n+host = \"0.0.0.0\"\n+port = 3000",
            "priority": "normal",
        }]
        msg = format_session_start(events)
        assert "FIXES BY TEAMMATES" in msg
        assert "CONTEXT — Be aware" not in msg  # No passive CONTEXT section
        assert "+[server]" in msg
        assert "apply all" in msg.lower()

    def test_change_without_diff_in_context_section(self):
        """Events without diffs should stay in CONTEXT section."""
        events = [{
            "type": "change",
            "user": "pioneer",
            "result": "Modified config.toml (1 file: config.toml)",
            "priority": "normal",
        }]
        msg = format_session_start(events)
        assert "CONTEXT" in msg
        assert "FIXES BY TEAMMATES" not in msg

    def test_mixed_fixes_and_context(self):
        """Events with and without diffs should be separated."""
        events = [
            {
                "type": "change", "user": "a",
                "result": "Modified config.toml\nDiff:\n+[server]\n+port = 3000",
                "priority": "normal",
            },
            {
                "type": "discovery", "user": "b",
                "result": "Found endpoint issue",
                "priority": "normal",
            },
        ]
        msg = format_session_start(events)
        assert "FIXES BY TEAMMATES" in msg
        assert "CONTEXT" in msg
        assert "IMPORTANT:" in msg

    def test_footer_with_fixes_has_apply_instruction(self):
        """When fixes exist, footer should emphasize applying them all at once."""
        events = [{
            "type": "change", "user": "pioneer",
            "result": "Fixed config\nDiff:\n+key = value",
            "priority": "normal",
        }]
        msg = format_session_start(events)
        assert "apply all fixes" in msg.lower()
        assert "re-discover" in msg


class TestFormatPreToolUse:
    def test_empty_events_returns_none(self):
        assert format_pre_tool_use([], "src/auth/*") is None

    def test_correction_in_rules(self):
        events = [{"type": "correction", "user": "dev_a", "result": "don't modify", "priority": "normal"}]
        msg = format_pre_tool_use(events, "src/auth/*")
        assert "RULES for this scope" in msg
        assert "don't modify" in msg

    def test_high_priority_in_rules(self):
        events = [{"type": "discovery", "user": "dev_a", "result": "important thing", "priority": "high_priority"}]
        msg = format_pre_tool_use(events, "src/api/*")
        assert "[HIGH PRIORITY]" in msg
        assert "RULES for this scope" in msg

    def test_normal_discovery_in_context(self):
        events = [{"type": "discovery", "user": "dev_a", "result": "found issue", "priority": "normal"}]
        msg = format_pre_tool_use(events, "src/cache/*")
        assert "Related context" in msg
        assert "found issue" in msg

    def test_scope_in_header(self):
        events = [{"type": "change", "user": "dev_a", "result": "changed file", "priority": "normal"}]
        msg = format_pre_tool_use(events, "src/auth/*")
        assert "src/auth/*" in msg

    def test_diff_event_in_fixes_section(self):
        """PreToolUse should show events with diffs as FIXES."""
        events = [{
            "type": "change", "user": "pioneer",
            "result": "Modified config.toml\nDiff:\n+[server]\n+port = 3000",
            "priority": "normal",
        }]
        msg = format_pre_tool_use(events, "*")
        assert "FIXES BY TEAMMATES" in msg
        assert "+[server]" in msg
        assert "ALL" in msg

    def test_diff_event_apply_all_instruction(self):
        """PreToolUse FIXES should tell agent to fix everything at once."""
        events = [
            {
                "type": "change", "user": "pioneer",
                "result": "Modified config.toml\nDiff:\n+[server]\n+port = 3000",
                "priority": "normal",
            },
            {
                "type": "change", "user": "pioneer",
                "result": "Modified config.toml\nDiff:\n+[session]\n+store = memory",
                "priority": "normal",
            },
        ]
        msg = format_pre_tool_use(events, "*")
        assert "FIXES BY TEAMMATES" in msg
        assert "IMPORTANT" in msg
        assert "single edit" in msg.lower() or "ALL fixes" in msg
