# Overmind — Product Requirements Document

> Version: 1.0
> Date: 2026-03-26
> Status: Phase 1 In Progress

---

## 1. Product Overview

### 1.1 What is Overmind?

Overmind는 복수의 독립적 작업 주체(인간 개발자 또는 자율 에이전트)가 동일 프로젝트에서 병렬 작업할 때, **Claude Code 인스턴스 간 메모리를 실시간으로 동기화**하는 시스템이다.

두 개의 아티팩트로 구성된다:
- **Overmind Server**: 프로젝트 단위 메모리 중계 및 관리를 수행하는 self-hosted HTTP/MCP 서버
- **Overmind Plugin**: 각 Claude Code 인스턴스에서 push/pull/broadcast를 자동화하는 플러그인

### 1.2 Problem Statement

Claude Code는 개별 작업 주체에게 강력한 AI 코딩 환경을 제공하지만, 복수 주체가 동일 프로젝트에서 병렬 작업할 때:

1. **지식 단절**: 개발자 A의 3시간 삽질 결과를 B의 Claude는 모르고 동일 삽질 반복
2. **Intent 다형성**: 코드는 merge 됐지만, 각 Claude가 기억하는 "왜 이렇게 했는지"가 다름
3. **프로젝트 메모리 파편화**: 개인 일관성은 유지되나, 팀 전체 맥락이 분산됨
4. **Claude Code 속도에 의한 괴리 증폭**: 빠른 작업 속도로 브랜치 간 코드베이스 괴리가 기하급수적으로 확대

### 1.3 Solution

각 Claude 인스턴스가 **결론뿐 아니라 의사결정 과정 전체**를 JSONL 이벤트로 중앙 서버에 push하고, 다른 인스턴스가 이를 pull하여 자기 컨텍스트에서 해석한다. 결론만 알면 "뭘 해야 하는지"는 알지만, 과정을 알면 "뭘 하면 안 되는지"도 안다.

---

## 2. Target Users

### 2.1 Primary: 소규모 팀 (2-5명)

- 동일 프로젝트에서 Claude Code를 활발히 사용하는 개발자
- 각자 브랜치에서 작업하며 주기적으로 merge하는 워크플로우
- 팀 내 구두 소통의 Claude 자동화를 원하는 경우

### 2.2 Secondary: 멀티 에이전트 오케스트레이션

- Claude Code agent teams, git worktree 기반 병렬 세션
- CI/CD 파이프라인에서 자율 동작하는 복수 Claude 인스턴스
- 마스터 에이전트가 서브 에이전트를 조율하는 구조

### 2.3 Non-Target (Phase 1)

- 대규모 팀 (10명+) — context window 압박 미검증
- 서로 다른 프로젝트 간 교차 공유 — repo-scoped 설계
- 실시간 스트리밍 (SSE/WebSocket) 필요 케이스 — hook 기반 pull로 충분

---

## 3. Functional Requirements

### 3.1 Core — Memory Push/Pull

| ID | Requirement | Priority | Phase |
|----|-------------|----------|-------|
| F-01 | 에이전트가 JSONL 이벤트를 서버에 push할 수 있다 | P0 | 1 |
| F-02 | 에이전트가 다른 에이전트의 이벤트를 pull할 수 있다 | P0 | 1 |
| F-03 | Pull 시 repo_id로 격리된다 | P0 | 1 |
| F-04 | Pull 시 자기 자신의 이벤트를 제외할 수 있다 (exclude_user) | P0 | 1 |
| F-05 | Pull 시 파일 scope로 필터링할 수 있다 (glob 패턴) | P0 | 1 |
| F-06 | Pull 시 시간 범위로 필터링할 수 있다 (since) | P1 | 1 |
| F-07 | 동일 event id의 중복 push가 무시된다 | P0 | 1 |
| F-08 | Urgent broadcast가 pull 시 최상단에 정렬된다 | P1 | 1 |

### 3.2 Event Types

| ID | Requirement | Priority | Phase |
|----|-------------|----------|-------|
| F-10 | correction 이벤트: 에러 발생 → 해결 과정 기록 | P0 | 1 |
| F-11 | decision 이벤트: 대안 검토 → 선택 과정 기록 | P0 | 1 |
| F-12 | discovery 이벤트: 새 사실/제약사항 발견 기록 | P0 | 1 |
| F-13 | change 이벤트: 파일 구조 변경 기록 | P1 | 1 |
| F-14 | broadcast 이벤트: 긴급 전파 메시지 | P0 | 1 |

### 3.3 Broadcast

| ID | Requirement | Priority | Phase |
|----|-------------|----------|-------|
| F-20 | MCP tool로 broadcast를 전송할 수 있다 | P0 | 1 |
| F-21 | Slash command로 broadcast를 전송할 수 있다 | P1 | 1 |
| F-22 | Skill 자동 매칭("팀에 알려줘")으로 broadcast를 전송할 수 있다 | P2 | 1 |
| F-23 | priority(normal/urgent) 구분이 가능하다 | P1 | 1 |

### 3.4 Plugin Hooks

| ID | Requirement | Priority | Phase |
|----|-------------|----------|-------|
| F-30 | SessionStart에 자동 pull이 발생한다 | P0 | 1 |
| F-31 | SessionEnd에 자동 push가 발생한다 | P0 | 1 |
| F-32 | Write/Edit 시 해당 scope의 이벤트를 선제 pull한다 | P1 | 1 |
| F-33 | Pull 결과가 systemMessage로 Claude context에 주입된다 | P0 | 1 |

### 3.5 Dashboard

| ID | Requirement | Priority | Phase |
|----|-------------|----------|-------|
| F-40 | 웹 대시보드에서 repo별 통계를 볼 수 있다 | P1 | 1 |
| F-41 | Agent → Event → Scope 관계 그래프를 볼 수 있다 | P1 | 1 |
| F-42 | 다형성(같은 scope, 다른 intent)이 그래프에서 시각적으로 강조된다 | P1 | 1 |
| F-43 | 에이전트별 타임라인을 볼 수 있다 | P2 | 1 |
| F-44 | Repo 목록이 드롭다운으로 자동 로딩된다 | P1 | 1 |

### 3.6 Phase 2+ (계획)

| ID | Requirement | Priority | Phase |
|----|-------------|----------|-------|
| F-50 | 서버 측 서머리 생성 (경량 LLM) | P1 | 2 |
| F-51 | Pull 시 `?detail=lesson\|summary\|full` 지원 | P1 | 2 |
| F-52 | SQLite store로 이관 | P2 | 2 |
| F-53 | 피드백 점수 (relevance_score, prevented_error) | P1 | 2 |
| F-54 | 서버 측 다형성 사전 탐지 | P2 | 3 |
| F-55 | 자기평가 메타 리포트 자동 생성 | P2 | 3 |

---

## 4. Non-Functional Requirements

### 4.1 Performance

| ID | Requirement | Target |
|----|-------------|--------|
| NF-01 | Push latency (클라이언트 → 서버 저장 완료) | < 200ms |
| NF-02 | Pull latency (scope 필터 포함) | < 500ms |
| NF-03 | Dashboard 초기 로딩 | < 2s |
| NF-04 | 동시 접속 에이전트 수 (Phase 1) | 5명 이상 |

### 4.2 Reliability

| ID | Requirement | Target |
|----|-------------|--------|
| NF-10 | 서버 재시작 시 데이터 유실 없음 | JSONL file-based persistence |
| NF-11 | 서버 다운 시 플러그인 훅이 Claude 세션을 블록하지 않음 | Timeout 5s, graceful fallback |
| NF-12 | 동시 push race condition 없음 | Append-only + dedup |

### 4.3 Security

| ID | Requirement | Target |
|----|-------------|--------|
| NF-20 | 사내 네트워크에서만 접근 가능 | 배포 구성으로 해결 (bind host) |
| NF-21 | Push 시 민감 정보(API key 등) 필터링 | Phase 2 — 클라이언트 측 |
| NF-22 | Repo 간 데이터 격리 | repo_id 기반 디렉토리 분리 |

### 4.4 Compatibility

| ID | Requirement | Target |
|----|-------------|--------|
| NF-30 | Python 3.11+ | 서버 런타임 |
| NF-31 | Windows / macOS / Linux | 플러그인 훅 (Python 기반) |
| NF-32 | Claude Code MCP 프로토콜 호환 | FastMCP v3 streamable-http |

---

## 5. Success Criteria

### 5.1 Phase 1 Go/No-Go

Phase 1의 성공 여부는 기술적 구현 완료가 아니라 다음 두 가지 조건의 충족으로 판단한다:

1. **의도적 lesson 전파**: A가 push한 lesson이 B의 작업 맥락에서 실제로 표면화되는가. B의 Claude가 A의 lesson을 인지하고 유저에게 고지하거나 판단에 반영하는 것까지를 포함한다.

2. **피드백 점수 확보**: 전파된 lesson에 대해 relevance_score 또는 prevented_error 등의 피드백 신호가 기록되는가.

두 조건 모두 충족 → Phase 2 진행. 하나라도 미충족 → 실패 원인 분석 후 Phase 1 재실행.

### 5.2 핵심 KPI (Phase 2+)

| KPI | 정의 | 목표 |
|-----|------|------|
| Context hit rate | Pull 시 유용한 이벤트 포함 비율 | > 80% |
| Sync latency | 이벤트 생성 → 다른 클라이언트 수신 시간 | < 5분 |
| Prevented error rate | 사전 차단이 발생한 세션 비율 | Baseline 확보 |
| Knowledge reuse ratio | 복수 클라이언트가 소비한 이벤트 / 전체 | > 50% |

---

## 6. JSONL Event Schema

```json
{
  "id": "string (uuid4)",
  "repo_id": "string (normalized git remote URL)",
  "user": "string (agent/developer identifier)",
  "ts": "string (ISO 8601)",
  "type": "decision | correction | discovery | change | broadcast",
  "result": "string (핵심 결론)",

  "prompt": "string? (작업 맥락 요약)",
  "files": "string[]? (관련 파일 경로)",
  "process": "string[]? (과정 기록: 시도 → 실패 → 해결)",
  "priority": "normal | urgent",
  "scope": "string? (명시적 scope)"
}
```

---

## 7. API Surface

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/memory/push` | JSONL 이벤트 push |
| GET | `/api/memory/pull` | Scope/since/user 기반 이벤트 pull |
| POST | `/api/memory/broadcast` | Urgent 전파 |
| GET | `/api/repos` | 등록된 repo 목록 |
| GET | `/api/report` | Repo별 통계 |
| GET | `/api/report/graph` | 그래프 시각화 데이터 |
| GET | `/api/report/timeline` | 타임라인 데이터 |
| MCP | `/mcp` | Claude Code MCP tool 노출 |
| Static | `/dashboard` | 웹 대시보드 |

---

## 8. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Context window 초과 (팀원 증가 시) | Claude 성능 저하 | Medium | Scope 필터링, limit, TTL 14일 |
| Push된 이벤트의 noise 비율이 높음 | Pull 시 유용한 정보 묻힘 | Medium | Phase 1에서 보수적 push (correction/decision/discovery만), Phase 2에서 서머리 |
| 서버 단일 장애점 | 팀 전체 sync 중단 | Low | 플러그인 graceful fallback (서버 다운 시 훅이 조용히 실패) |
| 민감 정보가 이벤트에 포함 | 보안 위험 | Medium | Phase 2에서 클라이언트 측 필터링, 사내 네트워크 운영 |
| 다형성 오탐지 | 불필요한 경고로 피로감 | Low | 클라이언트 Claude가 맥락 기반 판단, 서버는 데이터만 제공 |

---

## 9. Phased Delivery

### Phase 1: PoC (현재)
- Overmind Server (REST + MCP + Dashboard)
- Overmind Plugin (Hooks + Skills + Commands)
- 2인 환경에서 기본 push/pull 사이클 검증
- **산출물**: 동작하는 서버 + 플러그인 + 33개 자동화 테스트

### Phase 2: Housekeeping + 과정 캡처 강화
- 서머리 생성 (경량 LLM)
- `?detail=lesson|summary|full` 파라미터
- SQLite store 이관
- 피드백 점수 축적

### Phase 3: Broadcast + 다형성 고도화
- 서버 측 다형성 사전 탐지
- 자기평가 메타 리포트
- 팀 규모 확장 테스트 (3인+)

---

## 10. Related Documents

| Document | Path | Purpose |
|----------|------|---------|
| Architecture Research | [`docs/research/overmind-research.md`](research/overmind-research.md) | 문제 분석, 기존 솔루션 비교, 아키텍처 설계 근거 |
| Phase 1 Design Spec | [`docs/design/phase1-design.md`](design/phase1-design.md) | 데이터 모델, API, 플러그인, 대시보드 상세 설계 |
| Phase 1 Implementation Plan | [`docs/plans/phase1-implementation.md`](plans/phase1-implementation.md) | TDD 기반 11개 태스크 구현 계획 |
