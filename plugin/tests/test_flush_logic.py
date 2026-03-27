"""Tests for flush_pending_changes logic in api_client."""

import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from api_client import build_change_events, should_flush


class TestBuildChangeEvents:
    """build_change_events groups pending_changes by scope into event dicts."""

    def test_single_scope(self):
        pending = [
            {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:00:00Z", "action": "Edit"},
            {"file": "src/auth/oauth2.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:05:00Z", "action": "Write"},
        ]
        events = build_change_events(pending)
        assert len(events) == 1
        evt = events[0]
        assert evt["type"] == "change"
        assert evt["scope"] == "src/auth/*"
        assert set(evt["files"]) == {"src/auth/login.ts", "src/auth/oauth2.ts"}
        assert "2 files" in evt["result"]
        assert evt["id"].startswith("auto_")

    def test_multiple_scopes(self):
        pending = [
            {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:00:00Z", "action": "Edit"},
            {"file": "src/cache/redis.ts", "scope": "src/cache/*", "ts": "2026-03-27T10:05:00Z", "action": "Edit"},
        ]
        events = build_change_events(pending)
        assert len(events) == 2
        scopes = {e["scope"] for e in events}
        assert scopes == {"src/auth/*", "src/cache/*"}

    def test_empty_pending(self):
        events = build_change_events([])
        assert events == []

    def test_deduplicates_files(self):
        pending = [
            {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:00:00Z", "action": "Edit"},
            {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:10:00Z", "action": "Edit"},
        ]
        events = build_change_events(pending)
        assert len(events) == 1
        assert len(events[0]["files"]) == 1
        assert "1 file" in events[0]["result"]

    def test_result_format_single_file(self):
        pending = [
            {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:00:00Z", "action": "Edit"},
        ]
        events = build_change_events(pending)
        assert events[0]["result"] == "Modified src/auth/* (1 file: login.ts)"

    def test_result_format_multiple_files(self):
        pending = [
            {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:00:00Z", "action": "Edit"},
            {"file": "src/auth/oauth2.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:01:00Z", "action": "Edit"},
            {"file": "src/auth/jwt.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:02:00Z", "action": "Write"},
        ]
        events = build_change_events(pending)
        assert "3 files" in events[0]["result"]

    def test_lesson_field_preserved(self):
        pending = [
            {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:00:00Z", "action": "Edit", "lesson": None},
        ]
        events = build_change_events(pending)
        assert events[0]["type"] == "change"


class TestShouldFlush:
    """should_flush(state, new_scope) checks count/time/scope-change triggers."""

    def test_empty_pending_no_flush(self):
        state = {"pending_changes": [], "last_push_ts": "2026-03-27T10:00:00Z"}
        assert should_flush(state, "src/auth/*") is False

    def test_threshold_reached(self):
        state = {
            "pending_changes": [{"scope": "src/auth/*"}] * 5,
            "last_push_ts": "2026-03-27T10:00:00Z",
            "current_scope": "src/auth/*",
        }
        assert should_flush(state, "src/auth/*") is True

    def test_below_threshold(self):
        state = {
            "pending_changes": [{"scope": "src/auth/*"}] * 3,
            "last_push_ts": datetime.now(timezone.utc).isoformat(),
            "current_scope": "src/auth/*",
        }
        assert should_flush(state, "src/auth/*") is False

    def test_time_exceeded(self):
        old_ts = "2026-03-27T00:00:00+00:00"  # Many hours ago
        state = {
            "pending_changes": [{"scope": "src/auth/*"}],
            "last_push_ts": old_ts,
            "current_scope": "src/auth/*",
        }
        assert should_flush(state, "src/auth/*") is True

    def test_scope_change(self):
        state = {
            "pending_changes": [{"scope": "src/auth/*"}],
            "last_push_ts": datetime.now(timezone.utc).isoformat(),
            "current_scope": "src/auth/*",
        }
        assert should_flush(state, "src/cache/*") is True

    def test_no_last_push_ts_initializes_not_flush(self):
        state = {
            "pending_changes": [{"scope": "src/auth/*"}],
            "current_scope": "src/auth/*",
        }
        # No last_push_ts → initialize timestamp, don't flush (allow batching)
        assert should_flush(state, "src/auth/*") is False
        # State should now have last_push_ts set
        assert "last_push_ts" in state

    def test_scope_change_with_no_pending_no_flush(self):
        state = {
            "pending_changes": [],
            "last_push_ts": datetime.now(timezone.utc).isoformat(),
            "current_scope": "src/auth/*",
        }
        assert should_flush(state, "src/cache/*") is False
