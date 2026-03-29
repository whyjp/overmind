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
| Server | 95 | models 12, store 22+8(branch), api 13, mcp 6, scenarios 28, summary 2, branch_conflict 4 |
| Scaffold | 11 | branch_conflict check_config 6 + create_scaffold 5 |
| Plugin | 117 | api_client 27, flush 22, formatter 15, context_writer 8, diff_collector 6, conflict_detector 19, hooks 11 |
| E2E Live | 3+3+1 시나리오 | 기존 AB 3개 + statistical 3개 + branch-aware 1개 (`claude` CLI 필요) |
| **합계** | **222+** | |

---

## Statistical AB 벤치마크 결과 (2026-03-29)

### Model-Tier 벤치마크 (최적 방법론)

Pioneer=sonnet(상위모델) + SHARED_PROMPT → Student/Naive=haiku(하위모델). 프롬프트 조작 없이 모델 차이만으로 Overmind 가치 증명.

| Scaffold | Pioneer | Student vs Naive (시도) | Student vs Naive (성공) |
|----------|:---:|:---:|:---:|
| **nightmare** | sonnet, 2회 성공 | **-41% 서버 실행** | **100% vs 50%** |
| **branch_conflict** | sonnet, 1회 성공 | **-30% 서버 실행** | 100% vs 100% |

### PIONEER_PROMPT 방식 (레거시)

| Scaffold | 트랩 | Pioneer 프롬프트 | Student vs Naive |
|----------|------|:---:|---|
| simple (N=2,M=2) | 3 | SHARED | **없음** — 단순 트랩 |
| multistage (N=2,M=2) | 9 | SHARED | **없음** — 반복 패턴 |
| **nightmare (N=3,M=3)** | **5** | **PIONEER** | **-23% 시간, 33% vs 0% 성공** |

**인사이트**: Model-Tier가 PIONEER_PROMPT보다 설득력 있는 벤치마크. 상위 모델이 자연스럽게 더 나은 해결 과정 생성 → Overmind 자동 전파 → 하위 모델의 시행착오 감소 + 성공률 증가.

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

### 2. ✅ Branch-aware E2E 검증 (완료)
- `branch_conflict` scaffold: feat/auth ↔ feat/api 간 3가지 공유 리소스 충돌 트랩
  - TRAP 1: Port conflict (둘 다 8080 힌트)
  - TRAP 2: SERVICE_TOKEN 형식 충돌 (HS256 vs UUID)
  - TRAP 3: Session timeout 상호 배제 (auth ≥ 3600, api ≤ 1800)
- `test_branch_aware_ab()`: Pioneer(feat/auth) → Student/Naive(feat/api) cross-branch E2E
- 11 단위 테스트 (check_config 6 + create_scaffold 5)
- `port_conflict_count` metric 추가
- 다음: `--student-n 2 --naive-m 2` live AB 테스트 실행

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
| Infra | `ab_scaffolds/` | 5 scaffold 모듈 (simple, multistage, complex, nightmare, branch_conflict) |
| Infra | `ab_runner.py` | 공통 agent runner + 통계 + port_conflict_count metric |
| New | `test_live_agents_AB_statistical.py` | N/M 병렬 통계 테스트 + branch-aware E2E |
| New | `ab_scaffolds/branch_conflict.py` | cross-branch 3트랩 scaffold (feat/auth ↔ feat/api) |
| New | `ab_scaffolds/test_branch_conflict.py` | branch_conflict 단위 테스트 11개 |
