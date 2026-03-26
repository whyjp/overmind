import pytest
from overmind.models import MemoryEvent, PushRequest, BroadcastRequest


class TestMemoryEvent:
    def test_valid_event_minimal(self):
        evt = MemoryEvent(
            id="evt_001",
            repo_id="github.com/user/project",
            user="dev_a",
            ts="2026-03-26T05:30:22Z",
            type="correction",
            result=".env에 SERVICE_A_INTERNAL_URL 필요",
        )
        assert evt.id == "evt_001"
        assert evt.type == "correction"

    def test_valid_event_full(self):
        evt = MemoryEvent(
            id="evt_002",
            repo_id="github.com/user/project",
            user="dev_a",
            ts="2026-03-26T05:30:22Z",
            type="decision",
            result="OAuth2 기반으로 전환",
            prompt="인증 방식 전환",
            files=["src/auth/oauth2.ts", "src/auth/jwt.ts"],
            process=["JWT 검토→복잡도 과다", "세션 기반→stateless 충돌", "OAuth2+PKCE 채택"],
            priority="normal",
            scope="src/auth/*",
        )
        assert evt.files == ["src/auth/oauth2.ts", "src/auth/jwt.ts"]
        assert len(evt.process) == 3

    def test_invalid_type_rejected(self):
        with pytest.raises(ValueError):
            MemoryEvent(
                id="evt_003",
                repo_id="github.com/user/project",
                user="dev_a",
                ts="2026-03-26T05:30:22Z",
                type="invalid_type",
                result="test",
            )

    def test_missing_required_field(self):
        with pytest.raises(ValueError):
            MemoryEvent(
                id="evt_004",
                repo_id="github.com/user/project",
                user="dev_a",
                ts="2026-03-26T05:30:22Z",
                type="correction",
                # result missing
            )


class TestPushRequest:
    def test_valid_push(self):
        req = PushRequest(
            repo_id="github.com/user/project",
            user="dev_a",
            events=[
                {
                    "id": "evt_001",
                    "type": "correction",
                    "ts": "2026-03-26T05:30:22Z",
                    "result": "test result",
                }
            ],
        )
        assert len(req.events) == 1
        assert req.events[0].repo_id == "github.com/user/project"
        assert req.events[0].user == "dev_a"


class TestBroadcastRequest:
    def test_valid_broadcast(self):
        req = BroadcastRequest(
            repo_id="github.com/user/project",
            user="master_agent",
            message="API 스키마 v2로 변경",
            priority="urgent",
            scope="src/api/*",
            related_files=["src/api/schema.ts"],
        )
        assert req.priority == "urgent"

    def test_default_priority(self):
        req = BroadcastRequest(
            repo_id="github.com/user/project",
            user="dev_a",
            message="test broadcast",
        )
        assert req.priority == "normal"
