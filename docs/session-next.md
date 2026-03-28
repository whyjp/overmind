# Overmind — 다음 세션 브리핑

**마지막 업데이트**: 2026-03-28
**현재 브랜치**: main

---

## 전체 진행 상태

### Phase 1: ✅ 완료
- [x] Server (FastAPI + FastMCP + SQLite store)
- [x] Plugin (4 hooks: SessionStart, PreToolUse, PostToolUse, SessionEnd)
- [x] Dashboard (Overview + Flow View + SSE live)
- [x] 2인 환경 검증, Plugin 설치 테스트
- [x] Multi-agent integration test (hook sim + Claude CLI)

### Phase 2-A: ✅ 서버 데이터 품질 개선 (완료)
- [x] `?detail=summary|full` pull 파라미터
- [x] 서버 측 서머리 생성 (SummaryGenerator Protocol + MockSummaryGenerator)
- [x] SQLite store 이관
- [x] 피드백 점수 (prevented_error, helpful/irrelevant) 축적
- [x] Push "why" 보강 (diff_collector + PostToolUse context capture)
- [ ] PostToolUse lesson 필드 활용 → Phase 3으로 이관

### Phase 2-B: ✅ 클라이언트 레슨 반영 (완료)
- [x] `.claude/overmind-context.md` 동기화 (TTL 기반)
- [x] 구조화된 레슨 포맷 — `StructuredLesson {action, target, reason, replacement}`
- [x] pull 측 충돌 감지 — `conflict_detector.py` (deny/warn/ignore + legacy scope-aware fallback)
- [x] `overmind_memory` MCP tool — 팀 메모리 마크다운 조회 (scope 필터 지원)
- [ ] 장기: Claude Code 플러그인 메모리 API 지원 시 네이티브 통합

### 설계 인사이트: ✅ 모두 반영
- [x] Delta-only pull (`since` + `last_pull_ts`)
- [x] `detail` 파라미터
- [x] 서머리 생성 (SummaryGenerator Protocol)
- [x] `urgent` → `high_priority` 리네이밍
- [x] Scope 상대경로 정규화 (git root 기준)
- [x] Formatter 사실적 표현 전환 (FIXES → TEAMMATE CHANGES)

### Phase 3: Branch-Aware Selective Intelligence (미시작)
- [ ] Branch metadata: MemoryEvent에 `current_branch`, `base_branch` 추가
- [ ] 이벤트 타입 분화: `change` vs `discovery` vs `intent`
- [ ] Pull relevance 판단: 같은 base 분기 + 파일/모듈 겹침 우선순위
- [ ] 선택적 수용: PreToolUse에서 관련 이벤트 context 제공
- [ ] PostToolUse lesson 필드 활용 (Phase 2-A에서 이관)

---

## 테스트 현황

| 영역 | 수 | 내역 |
|------|-----|------|
| Server | 82 | models 12, store 14, api 13, mcp 6, scenarios 28, summary 2, 기타 |
| Plugin | 100 | api_client 20, flush 14, formatter 13, context_writer 8, diff_collector 6, conflict_detector 18, hooks 11, 기타 |
| E2E Live | 3 시나리오 | AB, AB_multistage, AB_complex (`claude` CLI 필요) |
| **합계** | **182+** | |

---

## 다음 세션 추천 작업

### Phase 3 진입 전 정리
1. **A/B 벤치마크 v2 실행 데이터 수집** — 8단계 캐스케이드 10회 반복 (haiku/sonnet)
2. **영향 측정 메커니즘** — cross-agent 이벤트가 실제 agent 행동을 바꿨는지 검증

### Phase 3 시작
3. **Branch metadata** — git branch 자동 감지, MemoryEvent에 `current_branch`/`base_branch` 추가
4. **Pull relevance 판단** — 같은 base branch 이벤트 필터링

---

## 핵심 변경 맵 (이번 세션)

| 영역 | 파일 | 변경 |
|------|------|------|
| Model | `server/overmind/models.py` | +StructuredLesson, +lesson field on MemoryEvent/PushEventInput |
| Store | `server/overmind/store.py` | +lesson 컬럼 (DB 스키마 + migration + push/pull 직렬화) |
| MCP | `server/overmind/mcp_server.py` | +overmind_memory tool, +_format_memory_resource |
| Hook | `plugin/hooks/on_pre_tool_use.py` | conflict_detector 통합 (deny/warn/ignore) |
| New | `plugin/scripts/conflict_detector.py` | 구조화된 레슨 기반 충돌 감지 |
| Rename | 20+ files | Priority "urgent" → "high_priority" |
| Formatter | `plugin/scripts/formatter.py` | FIXES → TEAMMATE CHANGES (사실적 표현) |
| Test | `plugin/tests/test_conflict_detector.py` | 18개 테스트 신규 |
| Test | `server/tests/scenarios/test_hooks_e2e.py` | +structured lesson E2E (prohibit/replace) |
