"""Tests for conflict_detector module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from conflict_detector import detect_conflict


class TestProhibitAction:
    def test_prohibit_file_match_denies(self):
        events = [{"id": "e1", "result": "no deploy edits", "lesson": {
            "action": "prohibit", "target": "src/deploy/*", "reason": "CI managed",
        }}]
        verdict, matching = detect_conflict("Edit", {"file_path": "src/deploy/config.sh"}, events)
        assert verdict == "deny"
        assert len(matching) == 1

    def test_prohibit_content_match_denies(self):
        events = [{"id": "e1", "result": "do not delete ButtonA", "lesson": {
            "action": "prohibit", "target": "ButtonA", "reason": "used by mobile",
        }}]
        verdict, _ = detect_conflict("Edit", {"file_path": "src/ui.tsx", "new_string": "removed ButtonA"}, events)
        assert verdict == "deny"

    def test_prohibit_no_match_ignores(self):
        events = [{"id": "e1", "result": "no deploy edits", "lesson": {
            "action": "prohibit", "target": "src/deploy/*", "reason": "CI managed",
        }}]
        verdict, _ = detect_conflict("Edit", {"file_path": "src/auth/login.ts"}, events)
        assert verdict == "ignore"


class TestReplaceAction:
    def test_replace_old_target_warns(self):
        events = [{"id": "e1", "result": "use argon2", "lesson": {
            "action": "replace", "target": "bcrypt", "reason": "security",
            "replacement": "argon2",
        }}]
        verdict, matching = detect_conflict(
            "Write", {"file_path": "src/auth.ts", "content": "import bcrypt from 'bcrypt'"}, events
        )
        assert verdict == "warn"
        assert len(matching) == 1

    def test_replace_using_replacement_ignores(self):
        events = [{"id": "e1", "result": "use argon2", "lesson": {
            "action": "replace", "target": "bcrypt", "reason": "security",
            "replacement": "argon2",
        }}]
        verdict, _ = detect_conflict(
            "Write", {"file_path": "src/auth.ts", "content": "import argon2 from 'argon2'"}, events
        )
        assert verdict == "ignore"


class TestAvoidAction:
    def test_avoid_target_in_content_warns(self):
        events = [{"id": "e1", "result": "Redis v3 memory leak", "lesson": {
            "action": "avoid", "target": "redis@3", "reason": "memory leak",
        }}]
        verdict, _ = detect_conflict(
            "Bash", {"file_path": "package.json", "command": "npm install redis@3"}, events
        )
        assert verdict == "warn"

    def test_avoid_no_match_ignores(self):
        events = [{"id": "e1", "result": "Redis v3 leak", "lesson": {
            "action": "avoid", "target": "redis@3", "reason": "memory leak",
        }}]
        verdict, _ = detect_conflict(
            "Bash", {"file_path": "package.json", "command": "npm install redis@4"}, events
        )
        assert verdict == "ignore"


class TestRequireAction:
    def test_require_missing_target_warns(self):
        events = [{"id": "e1", "result": "input validation required", "lesson": {
            "action": "require", "target": "validateInput", "reason": "security policy",
        }}]
        verdict, _ = detect_conflict(
            "Edit", {"file_path": "src/api/users.ts", "new_string": "export function createUser(data) {"}, events
        )
        assert verdict == "warn"

    def test_require_target_present_ignores(self):
        events = [{"id": "e1", "result": "input validation required", "lesson": {
            "action": "require", "target": "validateInput", "reason": "security policy",
        }}]
        verdict, _ = detect_conflict(
            "Edit", {"file_path": "src/api/users.ts", "new_string": "validateInput(data)"}, events
        )
        assert verdict == "ignore"


class TestPreferAction:
    def test_prefer_always_ignores(self):
        events = [{"id": "e1", "result": "use factory pattern", "lesson": {
            "action": "prefer", "target": "factory pattern", "reason": "consistency",
        }}]
        verdict, _ = detect_conflict(
            "Edit", {"file_path": "src/service.ts", "new_string": "new Service()"}, events
        )
        assert verdict == "ignore"


class TestLegacyFallback:
    def test_high_priority_correction_matching_scope_denies(self):
        events = [{"id": "e1", "type": "correction", "priority": "high_priority",
                    "result": "do not modify deploy scripts",
                    "files": ["src/deploy/run.sh"]}]
        verdict, matching = detect_conflict("Edit", {"file_path": "src/deploy/run.sh"}, events)
        assert verdict == "deny"
        assert len(matching) == 1

    def test_high_priority_correction_unrelated_scope_ignores(self):
        events = [{"id": "e1", "type": "correction", "priority": "high_priority",
                    "result": "do not modify deploy scripts",
                    "files": ["src/deploy/run.sh"]}]
        verdict, _ = detect_conflict("Edit", {"file_path": "src/auth/login.ts"}, events)
        assert verdict == "ignore"

    def test_high_priority_no_files_denies(self):
        """Legacy event with no files/scope conservatively matches."""
        events = [{"id": "e1", "type": "correction", "priority": "high_priority",
                    "result": "critical fix"}]
        verdict, _ = detect_conflict("Edit", {"file_path": "src/anything.ts"}, events)
        assert verdict == "deny"

    def test_normal_priority_ignores(self):
        events = [{"id": "e1", "type": "correction", "priority": "normal",
                    "result": "some correction"}]
        verdict, _ = detect_conflict("Edit", {"file_path": "src/auth.ts"}, events)
        assert verdict == "ignore"


class TestMixedEvents:
    def test_deny_wins_over_warn(self):
        events = [
            {"id": "e1", "result": "no deploy", "lesson": {
                "action": "prohibit", "target": "src/deploy/*", "reason": "CI",
            }},
            {"id": "e2", "result": "use argon2", "lesson": {
                "action": "replace", "target": "bcrypt", "reason": "security",
                "replacement": "argon2",
            }},
        ]
        verdict, matching = detect_conflict(
            "Edit", {"file_path": "src/deploy/auth.ts", "new_string": "import bcrypt"}, events
        )
        assert verdict == "deny"

    def test_empty_events_ignores(self):
        verdict, _ = detect_conflict("Edit", {"file_path": "src/foo.ts"}, [])
        assert verdict == "ignore"

    def test_no_file_path_ignores(self):
        events = [{"id": "e1", "result": "no deploy", "lesson": {
            "action": "prohibit", "target": "src/deploy/*", "reason": "CI",
        }}]
        verdict, _ = detect_conflict("Edit", {}, events)
        assert verdict == "ignore"

    def test_case_insensitive_matching(self):
        events = [{"id": "e1", "result": "avoid BCrypt", "lesson": {
            "action": "avoid", "target": "BCrypt", "reason": "security",
        }}]
        verdict, _ = detect_conflict(
            "Edit", {"file_path": "src/auth.ts", "new_string": "import bcrypt"}, events
        )
        assert verdict == "warn"
