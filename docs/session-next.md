# Overmind — 다음 세션 브리핑

**마지막 업데이트**: 2026-03-29
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

### Phase 2-B: ✅ 클라이언트 레슨 반영 (완료)
- [x] `.claude/overmind-context.md` 동기화 (TTL 기반)
- [x] 구조화된 레슨 포맷 — `StructuredLesson {action, target, reason, replacement}`
- [x] pull 측 충돌 감지 — `conflict_detector.py` (deny/warn/ignore + legacy scope-aware fallback)
- [x] `overmind_memory` MCP tool — 팀 메모리 마크다운 조회 (scope 필터 지원)

### Phase 3: ✅ Branch-Aware Selective Intelligence (완료)
- [x] Branch metadata: `current_branch`/`base_branch` 자동 감지 + DB 저장
- [x] 이벤트 타입: `intent` 추가 (forward-looking 선언)
- [x] Pull relevance 3-tier: same branch > same base > different base
- [x] 선택적 수용: formatter PLANNED CHANGES + branch tag
- [x] Lesson 자동분류: action → event type 매핑

### Statistical AB Test Framework: ✅ 완료
- [x] ab_scaffolds/ — 3개 scaffold 모듈화 (simple/multistage/complex)
- [x] ab_runner.py — 공통 agent runner + JSONL 분석 + 통계 리포트
- [x] pytest 옵션: --student-n, --naive-m, --agent-model
- [x] test_live_agents_AB_statistical.py — parametrize × scaffold, N/M 병렬 반복
- [x] conflict_detector require action scope 필터 수정

---

## 테스트 현황

| 영역 | 수 | 내역 |
|------|-----|------|
| Server | 90 | models 12, store 22+8(branch), api 13, mcp 6, scenarios 28, summary 2 |
| Plugin | 117 | api_client 27, flush 22, formatter 15, context_writer 8, diff_collector 6, conflict_detector 19, hooks 11 |
| E2E Live | 3+3 시나리오 | 기존 AB 3개 + statistical parametrized 3개 (`claude` CLI 필요) |
| **합계** | **207+** | |

---

## Statistical AB 벤치마크 결과 (2026-03-29)

### 핵심 발견: 단계 수가 아닌 문제 복잡도가 중요

| Scaffold | 단계 | Pioneer runs | Student runs | Naive runs | Overmind 효과 |
|----------|------|:---:|:---:|:---:|---|
| simple (N=2,M=2) | 3 | 2 | 2.0 | 2.0 | **없음** — haiku가 바로 풀어버림 |
| multistage (N=2,M=2) | 9 | 7 | 7.0 | 7.0 | **없음** — 단계만 많고 각 트랩이 단순 |

**분석**: 현재 scaffold의 트랩은 에러 메시지가 솔루션을 직접 가리키고, 각 트랩이 독립적이라 LLM이 iterative discovery로 충분히 해결 가능. Overmind가 차이를 만들려면:

1. **비자명한 트랩** — 에러 메시지만으로는 해결책 유추 불가
2. **상호의존성** — A를 고치면 B가 깨지는 구조
3. **잘못된 단서** — 에러가 실제 원인과 다른 곳을 가리킴
4. **다단계 추론** — 여러 파일/시스템을 cross-reference해야 해결 가능

v1 벤치마크(2026-03-27)에서는 Student가 27% 빠르고 31% 적은 tool uses를 보였는데, 이는 당시 formatter가 "FIXES BY TEAMMATES" 섹션으로 diff를 직접 전달했기 때문. 현재 코드에서도 이 기능은 작동하지만, 트랩 자체가 단순하면 Naive도 빠르게 풀어버림.

---

## 다음 세션 추천 작업

### 1. 복잡한 scaffold 설계 (최우선)
현재 scaffold는 "config section 추가" 반복이라 Overmind 가치를 증명하기 어려움. 새 scaffold 필요:

**후보 시나리오:**
- **상호의존 config**: A 값이 B 값에 의존 (e.g., cache TTL < session TTL, port 충돌)
- **Misleading errors**: 에러가 가리키는 파일과 실제 원인 파일이 다름
- **환경 간 불일치**: .env + docker-compose.yml + config.toml 간 값 동기화
- **순서 의존성**: 모듈 초기화 순서에 따라 다른 에러 발생
- **숨겨진 제약조건**: 소스 코드를 읽어야만 알 수 있는 validation rule

### 2. Branch-aware E2E 검증
- 다른 branch에서 작업하는 2+ agent가 intent/discovery를 cross-branch로 공유하는지 검증
- statistical test framework에 branch scenario 추가

### 3. Dashboard branch 시각화
- Flow View에 branch 정보 표시, branch별 필터

---

## 핵심 변경 맵 (최근)

| 영역 | 파일 | 변경 |
|------|------|------|
| Model | `models.py` | +current_branch, +base_branch, +intent type |
| Store | `store.py` | +branch 컬럼, 3-tier pull relevance |
| API | `api.py` | +branch/base_branch pull 파라미터 |
| Plugin | `api_client.py` | +get_current_branch(), +get_base_branch() |
| Plugin | `on_session_start.py` | branch metadata 자동 첨부 |
| Plugin | `formatter.py` | +PLANNED CHANGES section, +branch tag |
| Test | `test_store.py` | +8 branch 테스트 |
| Infra | `ab_scaffolds/` | 3 scaffold 모듈 추출 |
| Infra | `ab_runner.py` | 공통 agent runner + 통계 |
| New | `test_live_agents_AB_statistical.py` | N/M 병렬 통계 테스트 |
