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

### 핵심 발견: 문제 복잡도 + Pioneer 프롬프트 전략이 핵심

| Scaffold | 트랩 | Pioneer 프롬프트 | Student elapsed | Naive elapsed | Overmind 효과 |
|----------|------|:---:|:---:|:---:|---|
| simple (N=2,M=2) | 3 | SHARED | 25.1s | 23.3s | **없음** — 단순 트랩 |
| multistage (N=2,M=2) | 9 | SHARED | 70.8s | 61.1s | **없음** — 반복 패턴 |
| **nightmare (N=3,M=3)** | **5** | **PIONEER** | **103.1s** | **133.4s** | **-23% 시간, 33% vs 0% 성공** |

**Nightmare 핵심 지표 (N=3, M=3, haiku)**:
- **saw_server_running**: Student 33% vs Naive 0% — Student만 성공
- **elapsed**: 103.1s vs 133.4s → **23% 빠름**
- **config_file_edits**: 8.7 vs 13.7 → **36% 적음**

**인사이트**: Pioneer를 "이미 문제를 풀어본 전문가"로 시뮬레이션하면, 양질의 해결 과정이 Overmind로 Student에게 자동 전파됨. 단순 반복 트랩에서는 효과 없지만, 상호의존 + misleading errors + 다단계 추론이 결합된 복잡한 문제에서 가치 발현.

---

## 다음 세션 추천 작업

### 1. ✅ Nightmare Config Scaffold (완료)
5가지 상호의존 트랩이 있는 복잡한 AB test scaffold 구현 완료:
- TRAP 1: Misleading error (db.py traceback → 실제 원인은 .env)
- TRAP 2: Cross-file SHA256 (SECRET_KEY ↔ secrets/hmac.key)
- TRAP 3: Mutual dependency (cache.ttl < session.timeout)
- TRAP 4: Three-way port conflict (server/metrics/health)
- TRAP 5: Three-hop plugin chain (config.toml → registry.json → .env)
- 18 tests, check_config() scoring, analyze_conversation multi-file 확장
- 다음: `--student-n 3 --naive-m 3` live AB 테스트로 30%+ 차이 검증

### 1b. ✅ Nightmare Live AB 테스트 (완료)
- N=3, M=3 haiku: Student 23% 빠름, 33% vs 0% 성공률, 36% 적은 config 수정
- PIONEER_PROMPT 전략 유효: 전문가 시뮬레이션 → 양질의 이벤트 전파
- 상세: `docs/benchmark-ab-test.md` Nightmare 섹션

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
